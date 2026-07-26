from __future__ import annotations

import asyncio
import json
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
        "geometry_family": ["spirogram"],
        "liss_freq_x": ["3"],
        "liss_freq_y": ["2"],
        "liss_delta": ["1.5708"],
        "rose_n": ["5"],
        "rose_d": ["1"],
        "sf_m": ["6"],
        "sf_n1": ["0.3"],
        "sf_n2": ["0.3"],
        "sf_n3": ["0.3"],
        "path_data": [""],
        "harm_freq_x": ["3.01"],
        "harm_freq_y": ["2"],
        "harm_delta": ["1.5708"],
        "harm_damping": ["0.02"],
        "harm_turns": ["12"],
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
        "color_flow_source": ["curvature"],
        "color_flow_swing": ["120"],
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
    # A blank designer opens on one component whose legend tracks its id and
    # curve family live, so it reads "shape spirogram" rather than a fixed label.
    assert "data-title-live" in blank.body.decode()
    assert "shape spirogram" in blank.body.decode()


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
    assert payload["actor"]["components"][0]["color_flow"] == {
        "source": "curvature",
        "swing_degrees": 120.0,
    }
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


SQUARE_PATH = "M 0 0 L 10 0 L 10 10 L 0 10 Z"


def test_path_actor_saves_inline_path_data(tmp_path: Path) -> None:
    fields = _designer_fields(edit_id="mark-tracer", name="Mark Tracer")
    fields.update(
        {
            "geometry_family": ["path"],
            "path_data": [SQUARE_PATH],
            "fixed_radius": [""],
            "moving_radius": [""],
            "pen_offset": [""],
        }
    )

    actor_id = save_library_actor(tmp_path, fields)

    assert actor_id == "mark-tracer"
    payload = yaml.safe_load(
        (tmp_path / LIBRARY / "mark-tracer.yaml").read_text(encoding="utf-8")
    )
    geometry = payload["actor"]["components"][0]["geometry"]
    assert geometry["family"] == "path"
    assert geometry["path_data"] == SQUARE_PATH
    assert "fixed_radius" not in geometry
    document = ActorLibraryDocument.model_validate(payload)
    assert document.actor.components[0].geometry.path_data == SQUARE_PATH


def _split_svg(svg_text: str):
    return asyncio.run(
        actors_routes.actors_svg_subpaths(
            _request("/actors/svg-subpaths", [("svg", svg_text)])
        )
    )


def test_svg_subpaths_endpoint_splits_markup_and_bare_path_data() -> None:
    svg = (
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 20 20">'
        '<path d="M 0 0 L 10 0 L 10 10 Z M 12 12 L 14 12" fill="none"/>'
        "</svg>"
    )
    response = _split_svg(svg)
    assert response.status_code == 200
    payload = json.loads(response.body)
    assert len(payload["subpaths"]) == 2
    assert payload["subpaths"][0]["closed"] is True
    assert payload["subpaths"][1]["closed"] is False
    for subpath in payload["subpaths"]:
        assert subpath["d"].lstrip()[0] in "Mm"

    bare = _split_svg(SQUARE_PATH)
    assert bare.status_code == 200
    assert len(json.loads(bare.body)["subpaths"]) == 1


def test_svg_subpaths_endpoint_caps_results_and_rejects_garbage() -> None:
    many = " ".join(f"M {i} 0 L {i} 5" for i in range(14))
    response = _split_svg(many)
    assert response.status_code == 200
    # Capped to match ActorConfig's 9-component maximum.
    assert len(json.loads(response.body)["subpaths"]) == 9

    garbage = _split_svg("this is not svg at all }{")
    assert garbage.status_code == 422
    assert json.loads(garbage.body)["errors"]

    empty = _split_svg("")
    assert empty.status_code == 422

    no_shapes = _split_svg(
        '<svg xmlns="http://www.w3.org/2000/svg"><text x="1" y="1">hi</text></svg>'
    )
    assert no_shapes.status_code == 422
    assert "no drawable elements" in json.loads(no_shapes.body)["errors"][0]


def test_svg_subpaths_endpoint_converts_basic_shapes() -> None:
    svg = (
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 100 100">'
        '<rect x="2" y="2" width="20" height="20" rx="4"/>'
        '<circle cx="50" cy="50" r="10"/>'
        '<ellipse cx="70" cy="20" rx="8" ry="4"/>'
        '<polygon points="10,80 30,80 20,95"/>'
        '<polyline points="40,80 60,80 60,95"/>'
        '<line x1="70" y1="80" x2="90" y2="95"/>'
        "</svg>"
    )
    response = _split_svg(svg)
    assert response.status_code == 200
    payload = json.loads(response.body)
    assert len(payload["subpaths"]) == 6
    # rect, circle, ellipse, polygon are closed; polyline and line stay open.
    assert [subpath["closed"] for subpath in payload["subpaths"]] == [
        True,
        True,
        True,
        True,
        False,
        False,
    ]
    for subpath in payload["subpaths"]:
        assert subpath["d"].lstrip()[0] in "Mm"


def test_svg_subpaths_endpoint_rejects_malformed_shape() -> None:
    bad = _split_svg(
        '<svg xmlns="http://www.w3.org/2000/svg"><circle cx="oops" r="4"/></svg>'
    )
    assert bad.status_code == 422
    assert "could not convert" in json.loads(bad.body)["errors"][0]


def test_svg_subpaths_layout_reconstructs_source_composition() -> None:
    import pytest

    svg = (
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 200 100">'
        '<circle cx="25" cy="50" r="20"/>'
        '<rect x="100" y="10" width="80" height="80"/>'
        "</svg>"
    )
    payload = json.loads(_split_svg(svg).body)
    circle, rect = payload["subpaths"]
    # Small circle left of center, big square right of center — anchors and
    # relative scale must reproduce the source layout, not the 3x3 grid.
    assert circle["anchor_x"] < 0.5 < rect["anchor_x"]
    assert circle["anchor_y"] == pytest.approx(0.5, abs=0.005)
    assert rect["anchor_y"] == pytest.approx(0.5, abs=0.005)
    assert circle["anchor_x"] == pytest.approx(0.176, abs=0.005)
    assert rect["anchor_x"] == pytest.approx(0.728, abs=0.005)
    assert circle["base_scale"] == pytest.approx(0.23, abs=0.02)
    assert rect["base_scale"] == pytest.approx(0.65, abs=0.03)
    assert rect["base_scale"] > circle["base_scale"]


def test_svg_subpaths_single_shape_centers() -> None:
    import pytest

    payload = json.loads(_split_svg(SQUARE_PATH).body)
    (entry,) = payload["subpaths"]
    assert entry["anchor_x"] == pytest.approx(0.5, abs=0.005)
    assert entry["anchor_y"] == pytest.approx(0.5, abs=0.005)
    assert 0.05 <= entry["base_scale"] <= 2


def test_svg_subpaths_applies_element_transforms() -> None:
    import pytest

    # Two identical glyphs placed by per-path transforms (a wordmark's
    # layout lives entirely in the transforms). Without applying them both
    # collapse onto the origin; with them the anchors spread left-to-right.
    svg = (
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 100 20">'
        '<path transform="translate(10,10)" d="M -3 -3 L 3 -3 L 3 3 L -3 3 Z"/>'
        '<path transform="translate(90,10)" d="M -3 -3 L 3 -3 L 3 3 L -3 3 Z"/>'
        "</svg>"
    )
    left, right = json.loads(_split_svg(svg).body)["subpaths"]
    assert left["anchor_x"] < 0.5 < right["anchor_x"]
    assert left["anchor_y"] == pytest.approx(0.5, abs=0.02)
    # The transformed d must carry the translation, not the local coords.
    assert "10" in left["d"] or "7" in left["d"]


def test_svg_subpaths_applies_group_transforms() -> None:
    import pytest

    # A group transform composes with the child's own transform.
    svg = (
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 100 100">'
        '<g transform="translate(50,0)">'
        '<circle cx="0" cy="50" r="5"/>'
        "</g>"
        "</svg>"
    )
    (entry,) = json.loads(_split_svg(svg).body)["subpaths"]
    # Circle drawn at local x=0 but shifted to x=50 (center of a 0..100 box).
    assert entry["anchor_x"] == pytest.approx(0.5, abs=0.02)


def test_maricopa_mark_asset_splits_into_traceable_subpaths() -> None:
    svg = (Path(__file__).parents[3] / "site/public/assets/maricopa-mark.svg").read_text(
        encoding="utf-8"
    )
    response = _split_svg(svg)
    assert response.status_code == 200
    payload = json.loads(response.body)
    # Rounded frame, record circle, letterform "M", underline bar — all closed.
    assert len(payload["subpaths"]) == 4
    assert all(subpath["closed"] for subpath in payload["subpaths"])


def test_harmonograph_actor_saves_family_geometry(tmp_path: Path) -> None:
    fields = _designer_fields(edit_id="pendulum-ghost", name="Pendulum Ghost")
    fields.update(
        {
            "geometry_family": ["harmonograph"],
            "harm_freq_x": ["3.05"],
            "harm_damping": ["0.035"],
            "harm_turns": ["18"],
            "fixed_radius": [""],
            "moving_radius": [""],
            "pen_offset": [""],
        }
    )

    actor_id = save_library_actor(tmp_path, fields)

    assert actor_id == "pendulum-ghost"
    payload = yaml.safe_load(
        (tmp_path / LIBRARY / "pendulum-ghost.yaml").read_text(encoding="utf-8")
    )
    geometry = payload["actor"]["components"][0]["geometry"]
    assert geometry["family"] == "harmonograph"
    assert geometry["harm_freq_x"] == 3.05
    assert geometry["harm_damping"] == 0.035
    assert geometry["harm_turns"] == 18
    assert "fixed_radius" not in geometry
    assert "path_data" not in geometry
    document = ActorLibraryDocument.model_validate(payload)
    assert document.actor.components[0].geometry.harm_freq_y == 2


def test_rose_actor_saves_family_geometry(tmp_path: Path) -> None:
    fields = _designer_fields(edit_id="rose-bloom", name="Rose Bloom")
    fields.update(
        {
            "geometry_family": ["rose"],
            "rose_n": ["7"],
            "rose_d": ["3"],
            "fixed_radius": [""],
            "moving_radius": [""],
            "pen_offset": [""],
        }
    )

    actor_id = save_library_actor(tmp_path, fields)

    payload = yaml.safe_load(
        (tmp_path / LIBRARY / "rose-bloom.yaml").read_text(encoding="utf-8")
    )
    geometry = payload["actor"]["components"][0]["geometry"]
    assert geometry["family"] == "rose"
    assert geometry["rose_n"] == 7
    assert geometry["rose_d"] == 3
    assert "fixed_radius" not in geometry


def test_admin_and_renderer_revision_hashes_match(tmp_path: Path) -> None:
    """The admin's pin revision must equal the renderer-side auto-import's."""
    from mrp.admin.video_casting import _actor_revision
    from mrp.video.actor_library import actor_revision, load_library_actor

    directory = tmp_path / "assets" / "source" / "video" / "actors"
    directory.mkdir(parents=True)
    document = {
        "version": 1,
        "actor": {
            "id": "parity-check",
            "name": "Parity",
            "kind": "spirogram",
            "components": [
                {
                    "id": "shape",
                    "role": "vocals",
                    "geometry": {
                        "family": "spirogram",
                        "fixed_radius": 180,
                        "moving_radius": 60,
                        "pen_offset": 100,
                    },
                    "color": "#ffcc00",
                }
            ],
        },
    }
    (directory / "parity-check.yaml").write_text(
        yaml.safe_dump(document), encoding="utf-8"
    )
    actor = load_library_actor(tmp_path, "parity-check")
    assert actor_revision(actor) == _actor_revision(actor)
