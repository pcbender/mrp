import asyncio
import json
from pathlib import Path
from urllib.parse import urlencode

import pytest
import yaml
from starlette.requests import Request

from mrp.admin import gitops
from mrp.admin.routes import identity
from mrp.core.migrate_site import load_structured_record


def _request(path: str, method: str = "GET", fields: list[tuple[str, str]] | None = None) -> Request:
    body = urlencode(fields or []).encode()
    sent = False

    async def receive():
        nonlocal sent
        if sent:
            return {"type": "http.disconnect"}
        sent = True
        return {"type": "http.request", "body": body, "more_body": False}

    return Request({
        "type": "http",
        "asgi": {"version": "3.0"},
        "http_version": "1.1",
        "method": method,
        "scheme": "http",
        "path": path,
        "raw_path": path.encode(),
        "query_string": b"",
        "root_path": "",
        "headers": [(b"content-type", b"application/x-www-form-urlencoded")],
        "client": ("127.0.0.1", 1),
        "server": ("test", 80),
    }, receive)


def _write_artist(root: Path, artist: dict) -> Path:
    path = root / "content" / "artists" / f"{artist['id']}.yaml"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.safe_dump({"artist": artist}, sort_keys=False))
    return path


def _reference(root: Path, rel: str, contents: bytes = b"reference") -> Path:
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(contents)
    return path


def _candidate(root: Path, artist_id: str, name: str = "guid-123.jpg",
               member: str | None = None) -> Path:
    target = f"member-{member}" if member else "artist"
    path = (root / "assets/processed/identity" / artist_id / target /
            ("a" * 32) / "candidates" / name)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"generated")
    return path


def _solo(root: Path) -> dict:
    _reference(root, "assets/artists/stab/reference.jpg")
    return {
        "id": "stab",
        "name": "STAB",
        "type": "solo",
        "visibility": "public",
        "reference_image": "assets/artists/stab/reference.jpg",
        "likeness_notes": "Black bob haircut; angular features.",
        "image": "/assets/artists/stab/stab.png",
    }


def _band(root: Path) -> dict:
    _reference(root, "assets/artists/4castle/members/raven.jpg")
    _reference(root, "assets/artists/4castle/members/mack.jpg")
    return {
        "id": "4castle",
        "name": "4Castle",
        "type": "band",
        "visibility": "public",
        "members": [
            {
                "slug": "raven",
                "name": "Raven Cortez",
                "roles": ["vocals"],
                "reference_image": "assets/artists/4castle/members/raven.jpg",
                "likeness_notes": "Long dark hair.",
            },
            {
                "slug": "mack",
                "name": "Mack Bishop",
                "roles": ["guitar"],
                "reference_image": "assets/artists/4castle/members/mack.jpg",
                "likeness_notes": "Close-cropped silver hair.",
            },
        ],
    }


def test_assemble_solo_prompt_uses_likeness_and_direction(tmp_path):
    artist = _solo(tmp_path)
    prompt = identity.assemble_identity_prompt(artist, [artist], "Neon rehearsal room")
    assert "portrait of STAB" in prompt
    assert "Black bob haircut" in prompt
    assert "Neon rehearsal room" in prompt
    assert "No text" in prompt


def test_assemble_band_prompt_names_each_selected_member(tmp_path):
    artist = _band(tmp_path)
    prompt = identity.assemble_identity_prompt(artist, artist["members"], "Press photo")
    assert "group shot of 4Castle: Raven Cortez, Mack Bishop" in prompt
    assert "Raven Cortez: Long dark hair" in prompt
    assert "Mack Bishop: Close-cropped silver hair" in prompt
    assert "Maintain each person's distinct" in prompt


def test_assemble_member_prompt_targets_only_member(tmp_path):
    artist = _band(tmp_path)
    prompt = identity.assemble_identity_prompt(
        artist, [artist["members"][0]], "Stage portrait", target_member="raven")
    assert "portrait of Raven Cortez, a member of 4Castle" in prompt
    assert "Long dark hair" in prompt
    assert "Mack Bishop" not in prompt


def test_run_band_generation_uses_selected_references_and_count(tmp_path, monkeypatch):
    artist = _band(tmp_path)
    _write_artist(tmp_path, artist)
    captured = {}

    def fake_generate(**kwargs):
        captured.update(kwargs)
        output = kwargs["output_dir"] / "b0c4-guid.png"
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_bytes(b"candidate")
        return {
            "adapter": "mcp",
            "model": "test",
            "requested": kwargs["count"],
            "candidates": [{"file": str(output), "name": output.name}],
        }

    monkeypatch.setattr(identity.nim, "generate_identity_image", fake_generate)
    result = identity.run_identity_generation(
        tmp_path, "4castle", ["raven", "mack"], "Studio group portrait",
        count=3, request_id="b" * 32)

    assert [p.name for p in captured["references"]] == ["raven.jpg", "mack.jpg"]
    assert captured["count"] == 3
    assert "Raven Cortez, Mack Bishop" in captured["prompt"]
    assert result["candidates"][0]["file"].startswith(
        "assets/processed/identity/4castle/artist/")
    assert result["member_slugs"] == ["raven", "mack"]


def test_run_member_generation_uses_only_member_reference(tmp_path, monkeypatch):
    artist = _band(tmp_path)
    _write_artist(tmp_path, artist)
    captured = {}

    def fake_generate(**kwargs):
        captured.update(kwargs)
        output = kwargs["output_dir"] / "member-guid.webp"
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_bytes(b"candidate")
        return {"candidates": [{"file": str(output), "name": output.name}]}

    monkeypatch.setattr(identity.nim, "generate_identity_image", fake_generate)
    result = identity.run_identity_generation(
        tmp_path, "4castle", ["raven", "mack"], "", target_member="raven",
        request_id="c" * 32)

    assert [p.name for p in captured["references"]] == ["raven.jpg"]
    assert result["target_member"] == "raven"
    assert "member-raven" in result["candidates"][0]["file"]


def test_failed_generation_removes_ignored_staging_run(tmp_path, monkeypatch):
    _write_artist(tmp_path, _solo(tmp_path))
    run_dir = tmp_path / "assets/processed/identity/stab/artist" / ("d" * 32)

    def fail_generate(**kwargs):
        partial = kwargs["output_dir"] / "partial.png"
        partial.parent.mkdir(parents=True, exist_ok=True)
        partial.write_bytes(b"partial")
        raise identity.nim.NimGenerationError("generation failed")

    monkeypatch.setattr(identity.nim, "generate_identity_image", fail_generate)
    with pytest.raises(identity.nim.NimGenerationError, match="generation failed"):
        identity.run_identity_generation(
            tmp_path, "stab", [], "", request_id="d" * 32)
    assert not run_dir.exists()


def test_publish_artist_archives_guid_updates_stable_copy_and_yaml(tmp_path):
    artist = _solo(tmp_path)
    path = _write_artist(tmp_path, artist)
    old_public = _reference(tmp_path, "site/public/assets/artists/stab/stab.png", b"old")
    candidate = _candidate(tmp_path, "stab")

    result = identity.publish_identity_candidate(
        tmp_path, "stab", candidate.relative_to(tmp_path).as_posix())

    assert result["archive"] == "assets/artists/stab/generated/guid-123.jpg"
    assert (tmp_path / result["archive"]).read_bytes() == b"generated"
    assert (tmp_path / result["public"]).read_bytes() == b"generated"
    assert result["public"] == "site/public/assets/artists/stab/stab.jpg"
    assert not old_public.exists()
    saved = load_structured_record(path)["artist"]
    assert saved["image"] == "/assets/artists/stab/stab.jpg"
    assert not candidate.parent.parent.exists()


def test_publish_member_prefixes_archive_and_updates_member_only(tmp_path):
    artist = _band(tmp_path)
    path = _write_artist(tmp_path, artist)
    candidate = _candidate(tmp_path, "4castle", "nim-guid.webp", member="raven")

    result = identity.publish_identity_candidate(
        tmp_path, "4castle", candidate.relative_to(tmp_path).as_posix(), "raven")

    assert result["archive"] == "assets/artists/4castle/generated/raven-nim-guid.webp"
    assert result["public"] == "site/public/assets/artists/4castle/raven.webp"
    saved = load_structured_record(path)["artist"]
    assert saved.get("image") is None
    raven = next(m for m in saved["members"] if m["slug"] == "raven")
    mack = next(m for m in saved["members"] if m["slug"] == "mack")
    assert raven["image"] == "/assets/artists/4castle/raven.webp"
    assert mack.get("image") is None


def test_candidate_path_is_confined_to_artist_and_target(tmp_path):
    _write_artist(tmp_path, _band(tmp_path))
    candidate = _candidate(tmp_path, "other")
    with pytest.raises(identity.IdentityRefreshError, match="outside"):
        identity.publish_identity_candidate(
            tmp_path, "4castle", candidate.relative_to(tmp_path).as_posix())

    member_candidate = _candidate(tmp_path, "4castle", member="mack")
    with pytest.raises(identity.IdentityRefreshError, match="outside"):
        identity.publish_identity_candidate(
            tmp_path, "4castle", member_candidate.relative_to(tmp_path).as_posix(), "raven")


def test_reference_paths_reject_escape(tmp_path):
    outside = tmp_path.parent / "outside.jpg"
    outside.write_bytes(b"outside")
    artist = _solo(tmp_path)
    artist["reference_image"] = "../outside.jpg"
    with pytest.raises(identity.IdentityRefreshError, match="repository-relative"):
        identity._resolve_references(tmp_path, artist, [], [], None)


def test_discard_removes_last_candidate_and_run_uploads(tmp_path):
    candidate = _candidate(tmp_path, "stab")
    uploaded = candidate.parent.parent / "references" / "upload-1.jpg"
    uploaded.parent.mkdir(parents=True)
    uploaded.write_bytes(b"upload")
    identity.discard_identity_candidate(
        tmp_path, "stab", candidate.relative_to(tmp_path).as_posix())
    assert not candidate.parent.parent.exists()


def test_refresh_page_renders_band_and_member_modes(tmp_path, monkeypatch):
    _write_artist(tmp_path, _band(tmp_path))
    monkeypatch.setattr(identity, "get_repo_root", lambda: tmp_path)
    monkeypatch.setattr(identity.nim, "connected", lambda: True)
    band = asyncio.run(identity.identity_page(
        _request("/artists/4castle/refresh"), "4castle"))
    assert band.status_code == 200
    band_html = band.body.decode()
    assert "Raven Cortez" in band_html and "Mack Bishop" in band_html
    assert 'name="member_slugs"' in band_html
    assert "23 credits" in band_html
    assert "Nano Banana Pro Edit" in band_html
    assert "1:1" in band_html
    assert "2K" in band_html

    member = asyncio.run(identity.identity_page(
        _request("/artists/4castle/refresh"), "4castle", member="raven"))
    assert member.status_code == 200
    member_html = member.body.decode()
    assert "Raven Cortez" in member_html
    assert 'name="target_member" value="raven"' in member_html
    assert "Band Image" in member_html


def test_generate_route_launches_background_job_with_form_settings(tmp_path, monkeypatch):
    _write_artist(tmp_path, _band(tmp_path))
    monkeypatch.setattr(identity, "get_repo_root", lambda: tmp_path)
    captured = {}

    def fake_launch(command, fn, *args, **kwargs):
        captured.update(command=command, fn=fn, args=args, kwargs=kwargs)
        return "job-123"

    monkeypatch.setattr(identity.job_runner, "launch", fake_launch)
    monkeypatch.setattr(identity.db, "get_job", lambda job_id: {
        "id": job_id, "command": "identity/4castle/artist", "status": "pending", "output": None,
    })
    request = _request("/artists/4castle/refresh/generate", "POST", [
        ("member_slugs", "raven"),
        ("member_slugs", "mack"),
        ("count", "4"),
        ("prompt", "Desert at dusk"),
    ])
    response = asyncio.run(identity.identity_generate(request, "4castle"))

    assert response.status_code == 200
    assert "Generating artist candidates" in response.body.decode()
    assert captured["fn"] is identity.run_identity_generation
    assert captured["args"][2] == ["raven", "mack"]
    assert captured["kwargs"]["count"] == 4
    assert captured["kwargs"]["request_id"]


def test_review_poll_only_shows_confined_candidates(tmp_path, monkeypatch):
    _write_artist(tmp_path, _solo(tmp_path))
    candidate = _candidate(tmp_path, "stab")
    output = {
        "target_member": None,
        "references": 1,
        "candidates": [
            {"file": candidate.relative_to(tmp_path).as_posix(), "name": candidate.name},
            {"file": "assets/processed/identity/other/artist/x.png", "name": "x.png"},
        ],
    }
    monkeypatch.setattr(identity, "get_repo_root", lambda: tmp_path)
    monkeypatch.setattr(identity.db, "get_job", lambda job_id: {
        "id": job_id,
        "command": "identity/stab/artist",
        "status": "done",
        "output": json.dumps(output),
    })
    response = asyncio.run(identity.identity_poll(
        _request("/artists/stab/refresh/poll/job-1"), "stab", "job-1"))
    assert response.status_code == 200
    html = response.body.decode()
    assert html.count("guid-123.jpg") >= 1
    assert "x.png" not in html
    assert "/processed/identity/stab/artist/" in html
    assert "identity/other" not in html


def test_member_job_error_keeps_member_return_target(tmp_path):
    job = {
        "command": "identity/4castle/member-raven-cortez",
        "status": "error",
        "output": json.dumps({"status": "auth_required", "service": "nim", "message": "Connect."}),
    }
    context = identity._review_context(tmp_path, "4castle", job)
    assert context["target_member"] == "raven-cortez"
    assert context["return_to"] == "/artists/4castle/refresh?member=raven-cortez"


def test_changes_manages_stable_public_identity_images():
    assert gitops.is_data_path("site/public/assets/artists/stab/stab.jpg") is True
    assert gitops.is_data_path("site/public/styles/global.css") is False
    assert gitops.is_data_path("site/public/assets-elsewhere/file.jpg") is False
