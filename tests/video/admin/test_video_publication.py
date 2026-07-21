from __future__ import annotations

import asyncio
from pathlib import Path

import yaml

from mrp.admin.routes import video as video_routes
from mrp.core.migrate_site import load_structured_record
from tests.video.admin.test_video_casting import _get_request, _request
from tests.video.admin.test_video_rendering import _plan_job, _write_render_repo


def _artifact_path() -> str:
    return "assets/processed/video/artist--rendered-track/renders/full/full-1.mp4"


def test_publication_requires_opt_in_and_updates_only_selected_track(
    tmp_path: Path,
    monkeypatch,
) -> None:
    release, _track, release_path = _write_render_repo(tmp_path)
    cover = tmp_path / "assets" / "cover.jpg"
    cover.parent.mkdir(parents=True, exist_ok=True)
    cover.write_bytes(b"public poster bytes")
    media_root = tmp_path.parent / f"{tmp_path.name}-public-media"
    monkeypatch.setenv("MRP_PUBLIC_MEDIA_ROOT", str(media_root))
    monkeypatch.setattr(video_routes, "get_repo_root", lambda: tmp_path)
    _plan_job(tmp_path)
    untouched = release["tracks"][1].copy()

    approval = asyncio.run(
        video_routes.video_render_approve(
            _request(
                "/releases/render-release/tracks/rendered-track/video/rendering/approve",
                [("artifact_path", _artifact_path())],
            ),
            "render-release",
            "rendered-track",
        )
    )
    assert approval.status_code == 200

    approval_page = asyncio.run(
        video_routes.video_rendering(
            _get_request(
                "/releases/render-release/tracks/rendered-track/video/rendering"
            ),
            "render-release",
            "rendered-track",
        )
    ).body.decode()
    assert "Publish approved video" in approval_page
    assert 'name="opt_in" value="true" required' in approval_page
    assert 'name="opt_in" value="true" checked' not in approval_page

    rejected = asyncio.run(
        video_routes.video_render_publish(
            _request(
                "/releases/render-release/tracks/rendered-track/video/rendering/publish",
                [],
            ),
            "render-release",
            "rendered-track",
        )
    )
    assert rejected.status_code == 422
    assert not media_root.exists()

    published = asyncio.run(
        video_routes.video_render_publish(
            _request(
                "/releases/render-release/tracks/rendered-track/video/rendering/publish",
                [("opt_in", "true")],
            ),
            "render-release",
            "rendered-track",
        )
    )
    assert published.status_code == 200
    saved = load_structured_record(release_path)["release"]
    video = saved["tracks"][0]["music_video"]
    assert video["status"] == "published"
    assert video["opt_in"] is True
    assert video["public_url"].startswith(
        "/media/music-videos/artist--rendered-track/"
    )
    assert video["public_url"].endswith("/video.mp4")
    assert video["poster"].endswith(".jpg")
    assert saved["tracks"][1] == untouched

    public_video = media_root / video["public_url"].removeprefix("/media/")
    public_poster = media_root / video["poster"].removeprefix("/media/")
    assert public_video.read_bytes() == b"verified full bytes"
    assert public_poster.read_bytes() == b"public poster bytes"
    publication_path = (
        tmp_path
        / "assets/source/video/artist--rendered-track/publication.yaml"
    )
    publication = yaml.safe_load(publication_path.read_text(encoding="utf-8"))
    assert publication["opt_in"] is True
    assert publication["public_url"] == video["public_url"]
    assert "private" not in publication_path.read_text(encoding="utf-8").casefold()

    page = asyncio.run(
        video_routes.video_rendering(
            _get_request(
                "/releases/render-release/tracks/rendered-track/video/rendering"
            ),
            "render-release",
            "rendered-track",
        )
    )
    body = page.body.decode()
    assert "Public-media publication" in body
    assert "Opt In" in body
    assert "opted in" in body

    opted_out = asyncio.run(
        video_routes.video_render_visibility(
            _request(
                "/releases/render-release/tracks/rendered-track/video/rendering/visibility",
                [],
            ),
            "render-release",
            "rendered-track",
        )
    )
    assert opted_out.status_code == 200
    saved = load_structured_record(release_path)["release"]
    assert saved["tracks"][0]["music_video"]["opt_in"] is False
    assert public_video.is_file()
    assert public_poster.is_file()
    publication = yaml.safe_load(publication_path.read_text(encoding="utf-8"))
    assert publication["opt_in"] is False

    opted_in = asyncio.run(
        video_routes.video_render_visibility(
            _request(
                "/releases/render-release/tracks/rendered-track/video/rendering/visibility",
                [("opt_in", "true")],
            ),
            "render-release",
            "rendered-track",
        )
    )
    assert opted_in.status_code == 200
    saved = load_structured_record(release_path)["release"]
    assert saved["tracks"][0]["music_video"]["opt_in"] is True


def test_rendering_page_offers_publish_only_after_current_approval(
    tmp_path: Path,
    monkeypatch,
) -> None:
    _release, _track, _release_path = _write_render_repo(tmp_path)
    _plan_job(tmp_path)
    monkeypatch.setattr(video_routes, "get_repo_root", lambda: tmp_path)

    before = asyncio.run(
        video_routes.video_rendering(
            _get_request(
                "/releases/render-release/tracks/rendered-track/video/rendering"
            ),
            "render-release",
            "rendered-track",
        )
    ).body.decode()

    assert "Approval does not opt the track into public display" in before
    assert "Publish approved video" not in before
