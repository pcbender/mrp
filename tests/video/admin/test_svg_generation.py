from __future__ import annotations

import asyncio
import json
from pathlib import Path
from types import SimpleNamespace
from urllib.parse import urlencode

import pytest
from starlette.requests import Request

from mrp.admin import svg_gen
from mrp.admin.routes import actors as actors_routes
from mrp.admin.video_casting import CastingEditorError

VALID_SVG = (
    '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 512 512">'
    '<circle cx="256" cy="256" r="180"/>'
    '<path d="M 100 300 L 256 120 L 412 300"/>'
    "</svg>"
)


class FakeClient:
    """Duck-typed Anthropic client returning canned text responses."""

    def __init__(self, *texts: str):
        self.calls: list[dict] = []
        self._texts = list(texts)
        self.messages = SimpleNamespace(create=self._create)

    def _create(self, **kwargs):
        self.calls.append(kwargs)
        text = self._texts.pop(0)
        return SimpleNamespace(
            content=[
                SimpleNamespace(type="thinking", thinking="hmm"),
                SimpleNamespace(type="text", text=text),
            ]
        )


def test_generate_svg_shapes_happy_path(tmp_path: Path) -> None:
    client = FakeClient(f"Here is your mark:\n{VALID_SVG}\nEnjoy!")
    result = svg_gen.generate_svg_shapes(tmp_path, "a sun", client=client)

    assert result["svg"] == VALID_SVG
    assert len(result["subpaths"]) == 2
    assert result["subpaths"][0]["closed"] is True
    assert result["subpaths"][1]["closed"] is False
    call = client.calls[0]
    assert call["model"] == svg_gen.MODEL
    assert call["thinking"] == {"type": "adaptive"}
    assert "6" in call["system"]
    assert call["messages"] == [{"role": "user", "content": "a sun"}]


def test_generate_svg_shapes_retries_with_feedback(tmp_path: Path) -> None:
    client = FakeClient("Sorry, I painted a fresco instead.", VALID_SVG)
    result = svg_gen.generate_svg_shapes(tmp_path, "a sun", client=client)

    assert len(result["subpaths"]) == 2
    assert len(client.calls) == 2
    retry_messages = client.calls[1]["messages"]
    assert retry_messages[1]["role"] == "assistant"
    assert retry_messages[2]["role"] == "user"
    assert "failed validation" in retry_messages[2]["content"]


def test_generate_svg_shapes_fails_after_retry(tmp_path: Path) -> None:
    client = FakeClient("no shapes here", "still no shapes")
    with pytest.raises(CastingEditorError) as excinfo:
        svg_gen.generate_svg_shapes(tmp_path, "a sun", client=client)
    assert "failed after retry" in str(excinfo.value)
    assert len(client.calls) == 2


def test_generate_svg_shapes_enforces_subpath_cap(tmp_path: Path) -> None:
    many = "".join(f'<path d="M {i} 0 L {i} 5"/>' for i in range(8))
    client = FakeClient(f'<svg xmlns="http://www.w3.org/2000/svg">{many}</svg>')
    result = svg_gen.generate_svg_shapes(tmp_path, "lines", max_subpaths=3, client=client)
    assert len(result["subpaths"]) == 3
    assert "3" in client.calls[0]["system"]


def test_generate_svg_shapes_requires_brief(tmp_path: Path) -> None:
    with pytest.raises(CastingEditorError):
        svg_gen.generate_svg_shapes(tmp_path, "   ", client=FakeClient(VALID_SVG))


def _write_artist(root: Path, artist_id: str, **fields) -> None:
    import yaml

    directory = root / "content" / "artists"
    directory.mkdir(parents=True, exist_ok=True)
    payload = {"artist": {"id": artist_id, "name": fields.pop("name", artist_id), **fields}}
    (directory / f"{artist_id}.yaml").write_text(
        yaml.safe_dump(payload), encoding="utf-8"
    )


def test_artist_brief_includes_identity(tmp_path: Path) -> None:
    _write_artist(
        tmp_path,
        "4castle",
        name="4Castle",
        bio_short="A vast lyrical universe.",
        likeness_notes="Five recurring band members.",
    )
    brief = svg_gen.artist_brief(tmp_path, "4castle")
    assert '"4Castle"' in brief
    assert "A vast lyrical universe." in brief
    assert "Five recurring band members." in brief


def test_artist_brief_skips_null_likeness(tmp_path: Path) -> None:
    _write_artist(tmp_path, "pcbender", name="PCBender", likeness_notes=None)
    brief = svg_gen.artist_brief(tmp_path, "pcbender")
    assert '"PCBender"' in brief
    assert "Visual identity notes" not in brief


def test_artist_brief_missing_artist(tmp_path: Path) -> None:
    with pytest.raises(CastingEditorError):
        svg_gen.artist_brief(tmp_path, "ghost")


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


def test_svg_generate_route_returns_subpaths(tmp_path: Path, monkeypatch) -> None:
    _write_artist(tmp_path, "4castle", name="4Castle")
    monkeypatch.setattr(actors_routes, "get_repo_root", lambda: tmp_path)

    captured: dict = {}

    def fake_generate(root, brief, *, max_subpaths):
        captured["brief"] = brief
        captured["max_subpaths"] = max_subpaths
        return {"svg": VALID_SVG, "subpaths": [{"d": "M 0 0 L 1 1", "closed": False}]}

    monkeypatch.setattr(svg_gen, "generate_svg_shapes", fake_generate)

    response = asyncio.run(
        actors_routes.actors_svg_generate(
            _request(
                "/actors/svg-generate",
                [("artist_id", "4castle"), ("brief", "make it warm"), ("max_subpaths", "4")],
            )
        )
    )
    assert response.status_code == 200
    payload = json.loads(response.body)
    assert payload["subpaths"]
    assert '"4Castle"' in captured["brief"]
    assert "make it warm" in captured["brief"]
    assert captured["max_subpaths"] == 4


def test_svg_generate_route_requires_brief_or_artist(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(actors_routes, "get_repo_root", lambda: tmp_path)
    response = asyncio.run(
        actors_routes.actors_svg_generate(_request("/actors/svg-generate", []))
    )
    assert response.status_code == 422
    assert "requires a design brief" in json.loads(response.body)["errors"][0]
