from __future__ import annotations

import asyncio
import json
from pathlib import Path
from urllib.parse import urlencode

import pytest
from starlette.requests import Request

from mrp.admin.routes import actors as actors_routes
from mrp.admin.text_outline import resolve_font, text_to_path_data
from mrp.admin.video_casting import CastingEditorError
from mrp.video.geometry import SpiroGeometry, generate_text_points
from mrp.video.project import LayerGeometryConfig


def _font() -> Path:
    try:
        return resolve_font(Path("."))
    except CastingEditorError:
        pytest.skip("no usable system font for text outline")


def test_text_to_path_data_produces_multi_subpath() -> None:
    d = text_to_path_data("Ab", _font())
    # Two letters, each at least one contour -> at least two subpaths, all M-led.
    assert d.count("M") >= 2
    assert d.lstrip()[0] in "Mm"


def test_text_outline_feeds_the_text_geometry() -> None:
    d = text_to_path_data("4Castle", _font())
    config = LayerGeometryConfig(family="text", path_data=d, samples=120)
    contours = generate_text_points(
        SpiroGeometry(**config.model_dump(exclude_none=True))
    )
    # "4Castle" has counters (4, a, e) so more contours than letters.
    assert len(contours) >= 7


def test_text_outline_positions_glyphs_left_to_right() -> None:
    d = text_to_path_data("HI", _font())
    contours = generate_text_points(
        SpiroGeometry(
            **LayerGeometryConfig(
                family="text", path_data=d, samples=120
            ).model_dump(exclude_none=True)
        )
    )
    centers = sorted(sum(p.x for p in contour) / len(contour) for contour in contours)
    # The two letters occupy distinct horizontal bands.
    assert centers[0] < 0 < centers[-1]


def test_text_outline_rejects_empty() -> None:
    with pytest.raises(CastingEditorError):
        text_to_path_data("   ", _font())


def test_text_outline_rejects_spaces_only_word() -> None:
    with pytest.raises(CastingEditorError):
        text_to_path_data("\t \n", _font())


def _post(path: str, fields: list[tuple[str, str]]) -> Request:
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


def test_text_outline_route_returns_path_data(tmp_path: Path, monkeypatch) -> None:
    _font()  # skip if no font
    monkeypatch.setattr(actors_routes, "get_repo_root", lambda: tmp_path)
    response = asyncio.run(
        actors_routes.actors_text_outline(_post("/actors/text-outline", [("text", "Hi")]))
    )
    assert response.status_code == 200
    payload = json.loads(response.body)
    assert payload["path_data"].count("M") >= 2
    # The returned d validates as a text geometry.
    LayerGeometryConfig(family="text", path_data=payload["path_data"])


def test_text_outline_route_rejects_empty(tmp_path: Path, monkeypatch) -> None:
    _font()
    monkeypatch.setattr(actors_routes, "get_repo_root", lambda: tmp_path)
    response = asyncio.run(
        actors_routes.actors_text_outline(_post("/actors/text-outline", [("text", "  ")]))
    )
    assert response.status_code == 422
    assert json.loads(response.body)["errors"]
