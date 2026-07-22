from __future__ import annotations

import asyncio
from pathlib import Path
from urllib.parse import urlencode

import yaml
from starlette.requests import Request

from mrp.admin.routes import actors as actors_routes
from mrp.admin.video_casting import save_library_actor
from mrp.video.project import ActorConfig, ActorLibraryDocument

LIBRARY = Path("assets/source/video/actors")


def _request(path: str, fields: list[tuple[str, str]]) -> Request:
    body = urlencode(fields).encode()
    sent = False

    async def receive():
        nonlocal sent
        if sent:
            return {"type": "http.disconnect"}
        sent = True
        return {"type": "http.request", "body": body, "more_body": False}

    return Request(
        {
            "type": "http",
            "asgi": {"version": "3.0"},
            "http_version": "1.1",
            "method": "POST",
            "scheme": "http",
            "path": path,
            "raw_path": path.encode(),
            "query_string": b"",
            "root_path": "",
            "headers": [(b"content-type", b"application/x-www-form-urlencoded")],
            "client": ("127.0.0.1", 1),
            "server": ("test", 80),
        },
        receive,
    )


def _get_request(path: str) -> Request:
    return Request(
        {
            "type": "http",
            "asgi": {"version": "3.0"},
            "http_version": "1.1",
            "method": "GET",
            "scheme": "http",
            "path": path,
            "raw_path": path.encode(),
            "query_string": b"",
            "root_path": "",
            "headers": [],
            "client": ("127.0.0.1", 1),
            "server": ("test", 80),
        }
    )


def _designer_fields(
    *,
    action: str = "actor_save",
    original_id: str = "",
    edit_id: str = "rose-lantern",
    name: str = "Rose Lantern",
) -> dict[str, list[str]]:
    return {
        "action": [action],
        "actor_original_id": [original_id],
        "actor_edit_id": [edit_id],
        "actor_name": [name],
        "actor_description": ["A rose identity with a slow inner bloom."],
        "trace_id": ["shape"],
        "trace_role": ["vocals"],
        "fixed_radius": ["180"],
        "moving_radius": ["61"],
        "pen_offset": ["104"],
        "phase": ["0.5"],
        "geometry_rotation": ["inside"],
        "samples": ["900"],
        "cycles_per_second": ["0.08"],
        "trail_fraction": ["0.24"],
        "ghost_count": ["1"],
        "ghost_spacing": ["0.08"],
        "head_radius": ["3"],
        "color": ["#ff5fd2"],
        "depth": ["foreground"],
        "anchor_x": ["0.5"],
        "anchor_y": ["0.5"],
        "base_scale": ["1"],
        "opacity": ["0.8"],
        "line_width": ["2"],
        "rotation_speed": ["0"],
        "hue_shift": ["0"],
        "blend_mode": ["screen"],
        "driver_scale": [""],
        "driver_opacity": [""],
        "driver_color": [""],
        "driver_pulse": [""],
    }


def _post_fields(fields: dict[str, list[str]]) -> list[tuple[str, str]]:
    return [(name, value) for name, values in fields.items() for value in values]


def _seed_actor(root: Path, actor_id: str = "rose-lantern") -> Path:
    document = ActorLibraryDocument(
        actor=ActorConfig.model_validate(
            {
                "id": actor_id,
                "name": "Rose Lantern",
                "description": "Seeded identity.",
                "kind": "spirogram",
                "components": [
                    {
                        "id": "shape",
                        "role": "vocals",
                        "color": "#ff5fd2",
                        "geometry": {
                            "fixed_radius": 180,
                            "moving_radius": 61,
                            "pen_offset": 104,
                            "phase": 0.5,
                        },
                    }
                ],
            }
        )
    )
    path = root / LIBRARY / f"{actor_id}.yaml"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        yaml.safe_dump(document.model_dump(mode="json", exclude_none=True), sort_keys=False),
        encoding="utf-8",
    )
    return path


def _save(root: Path, fields: dict[str, list[str]]):
    return asyncio.run(
        actors_routes.actors_save(_request("/actors/save", _post_fields(fields)))
    )


def test_index_renders_headshot_grid_with_phase_shapes(tmp_path: Path, monkeypatch) -> None:
    _seed_actor(tmp_path)
    monkeypatch.setattr(actors_routes, "get_repo_root", lambda: tmp_path)

    page = asyncio.run(actors_routes.actors_index(_get_request("/actors")))

    body = page.body.decode()
    assert page.status_code == 200
    assert "Rose Lantern" in body
    assert "/actors/rose-lantern" in body
    assert "/actors/new" in body
    assert "data-shapes" in body
    assert '"phase": 0.5' in body
    assert "/static/spiro-preview.js" in body


def test_designer_renders_saved_actor_and_unknown_id_is_404(tmp_path: Path, monkeypatch) -> None:
    _seed_actor(tmp_path)
    monkeypatch.setattr(actors_routes, "get_repo_root", lambda: tmp_path)

    page = asyncio.run(
        actors_routes.actors_designer(_get_request("/actors/rose-lantern"), "rose-lantern")
    )
    body = page.body.decode()
    assert page.status_code == 200
    assert 'value="rose-lantern"' in body
    assert 'name="phase"' in body
    assert 'type="range"' in body
    assert 'name="actor_character"' not in body
    assert "spiro-play" in body

    missing = asyncio.run(
        actors_routes.actors_designer(_get_request("/actors/nope"), "nope")
    )
    assert missing.status_code == 404

    blank = asyncio.run(actors_routes.actors_new(_get_request("/actors/new")))
    assert blank.status_code == 200
    assert "New visual component" in blank.body.decode()


def test_save_writes_a_validated_library_file(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(actors_routes, "get_repo_root", lambda: tmp_path)

    response = _save(tmp_path, _designer_fields())

    assert response.status_code == 200
    assert response.headers["HX-Redirect"] == "/actors/rose-lantern"
    path = tmp_path / LIBRARY / "rose-lantern.yaml"
    payload = yaml.safe_load(path.read_text(encoding="utf-8"))
    assert "character" not in payload["actor"]
    assert "library_source" not in payload["actor"]
    assert payload["actor"]["components"][0]["geometry"]["phase"] == 0.5
    document = ActorLibraryDocument.model_validate(payload)
    assert document.actor.name == "Rose Lantern"


def test_blank_id_derives_from_name(tmp_path: Path) -> None:
    fields = _designer_fields(edit_id="", name="Neon Moth")

    actor_id = save_library_actor(tmp_path, fields)

    assert actor_id == "neon-moth"
    assert (tmp_path / LIBRARY / "neon-moth.yaml").is_file()


def test_rename_moves_the_library_file_and_collisions_are_rejected(
    tmp_path: Path, monkeypatch
) -> None:
    _seed_actor(tmp_path)
    _seed_actor(tmp_path, "other-actor")
    monkeypatch.setattr(actors_routes, "get_repo_root", lambda: tmp_path)

    renamed = _save(
        tmp_path,
        _designer_fields(original_id="rose-lantern", edit_id="lantern-prime"),
    )
    assert renamed.headers["HX-Redirect"] == "/actors/lantern-prime"
    assert not (tmp_path / LIBRARY / "rose-lantern.yaml").exists()
    assert (tmp_path / LIBRARY / "lantern-prime.yaml").is_file()

    collision = _save(
        tmp_path,
        _designer_fields(original_id="lantern-prime", edit_id="other-actor"),
    )
    assert collision.status_code == 422
    assert "already has an actor" in collision.body.decode()
    assert (tmp_path / LIBRARY / "lantern-prime.yaml").is_file()


def test_duplicate_creates_a_unique_copy(tmp_path: Path) -> None:
    _seed_actor(tmp_path)

    actor_id = save_library_actor(
        tmp_path, {"action": ["actor_duplicate"], "actor_original_id": ["rose-lantern"]}
    )

    assert actor_id == "rose-lantern-copy"
    payload = yaml.safe_load(
        (tmp_path / LIBRARY / "rose-lantern-copy.yaml").read_text(encoding="utf-8")
    )
    assert payload["actor"]["name"] == "Rose Lantern Copy"
    assert (tmp_path / LIBRARY / "rose-lantern.yaml").is_file()


def test_delete_unlinks_and_repeat_delete_is_a_validation_error(
    tmp_path: Path, monkeypatch
) -> None:
    _seed_actor(tmp_path)
    monkeypatch.setattr(actors_routes, "get_repo_root", lambda: tmp_path)
    fields = {"action": ["actor_delete"], "actor_original_id": ["rose-lantern"]}

    deleted = _save(tmp_path, fields)
    assert deleted.headers["HX-Redirect"] == "/actors"
    assert not (tmp_path / LIBRARY / "rose-lantern.yaml").exists()

    repeat = _save(tmp_path, fields)
    assert repeat.status_code == 422
    assert "does not exist" in repeat.body.decode()


def test_missing_name_is_a_validation_error(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(actors_routes, "get_repo_root", lambda: tmp_path)

    response = _save(tmp_path, _designer_fields(name=""))

    assert response.status_code == 422
    assert "actor name is required" in response.body.decode()
