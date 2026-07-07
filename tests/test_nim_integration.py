import json
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

import pytest

from mrp.admin import nim
from mrp.admin import pipeline as pipe

_ENDPOINTS = nim.OAuthEndpoints(
    resource="https://mcp.nim.example/mcp",
    authorize_url="https://nim.example/mcp/authorize",
    token_url="https://mcp.nim.example/api/mcp/oauth/token",
    registration_url="https://mcp.nim.example/api/mcp/oauth/register",
)


class _FakeResponse:
    def __init__(self, status_code=200, payload=None, headers=None, text=""):
        self.status_code = status_code
        self._payload = payload
        self.headers = headers or {}
        self.text = text

    def json(self):
        if self._payload is None:
            raise ValueError("no json")
        return self._payload


def test_begin_oauth_registers_client_and_stores_pkce_state(tmp_path, monkeypatch):
    monkeypatch.setenv("MRP_STATE_DIR", str(tmp_path / "state"))
    monkeypatch.setattr(nim, "discover", lambda url: _ENDPOINTS)

    registrations = []

    def fake_post(url, **kwargs):
        registrations.append((url, kwargs.get("json")))
        return _FakeResponse(payload={
            "client_id": "nim_mcp_client-123",
            "redirect_uris": kwargs["json"]["redirect_uris"],
        })

    monkeypatch.setattr(nim.requests, "post", fake_post)

    url = nim.begin_oauth(None, "http://127.0.0.1:8000", "/releases/a-good-day-to-be/promoter")
    parsed = urlsplit(url)
    query = parse_qs(parsed.query)

    assert registrations[0][0] == _ENDPOINTS.registration_url
    assert registrations[0][1]["token_endpoint_auth_method"] == "none"
    assert parsed.netloc == "nim.example"
    assert query["client_id"] == ["nim_mcp_client-123"]
    assert query["redirect_uri"] == ["http://127.0.0.1:8000/nim/oauth/callback"]
    assert query["code_challenge_method"] == ["S256"]
    assert query["resource"] == [_ENDPOINTS.resource]
    assert query["state"]

    pending = json.loads((tmp_path / "state" / "nim-oauth.json").read_text())
    assert pending["state"] == query["state"][0]
    assert pending["return_to"] == "/releases/a-good-day-to-be/promoter"
    assert pending["code_verifier"]
    assert pending["token_url"] == _ENDPOINTS.token_url

    client = json.loads((tmp_path / "state" / "nim-client.json").read_text())
    assert client["client_id"] == "nim_mcp_client-123"


def test_begin_oauth_reuses_registered_client(tmp_path, monkeypatch):
    state_dir = tmp_path / "state"
    monkeypatch.setenv("MRP_STATE_DIR", str(state_dir))
    monkeypatch.setattr(nim, "discover", lambda url: _ENDPOINTS)
    state_dir.mkdir(parents=True)
    (state_dir / "nim-client.json").write_text(json.dumps({
        "client_id": "nim_mcp_existing",
        "redirect_uris": ["http://127.0.0.1:8000/nim/oauth/callback"],
    }))

    def fail_post(url, **kwargs):
        raise AssertionError("should not re-register an already-registered client")

    monkeypatch.setattr(nim.requests, "post", fail_post)

    url = nim.begin_oauth(None, "http://127.0.0.1:8000", "/releases")
    assert parse_qs(urlsplit(url).query)["client_id"] == ["nim_mcp_existing"]


def test_finish_oauth_exchanges_code_and_stores_token(tmp_path, monkeypatch):
    state_dir = tmp_path / "state"
    monkeypatch.setenv("MRP_STATE_DIR", str(state_dir))
    state_dir.mkdir(parents=True)
    (state_dir / "nim-oauth.json").write_text(json.dumps({
        "state": "state-1",
        "code_verifier": "verifier-1",
        "return_to": "/releases/demo/promoter",
        "redirect_uri": "http://127.0.0.1:8000/nim/oauth/callback",
        "client_id": "nim_mcp_client-123",
        "token_url": _ENDPOINTS.token_url,
        "resource": _ENDPOINTS.resource,
    }))

    exchanges = []

    def fake_post(url, **kwargs):
        exchanges.append((url, kwargs.get("data")))
        return _FakeResponse(payload={"access_token": "tok-1", "expires_in": 3600})

    monkeypatch.setattr(nim.requests, "post", fake_post)

    return_to = nim.finish_oauth("code-1", "state-1")

    assert return_to == "/releases/demo/promoter"
    assert exchanges[0][0] == _ENDPOINTS.token_url
    assert exchanges[0][1]["code_verifier"] == "verifier-1"
    assert exchanges[0][1]["grant_type"] == "authorization_code"
    token = json.loads((state_dir / "nim-token.json").read_text())
    assert token["access_token"] == "tok-1"
    assert token["expires_at"] > 0
    assert token["token_url"] == _ENDPOINTS.token_url
    assert not (state_dir / "nim-oauth.json").exists()
    assert nim.connected()


def test_finish_oauth_rejects_state_mismatch(tmp_path, monkeypatch):
    state_dir = tmp_path / "state"
    monkeypatch.setenv("MRP_STATE_DIR", str(state_dir))
    state_dir.mkdir(parents=True)
    (state_dir / "nim-oauth.json").write_text(json.dumps({"state": "expected"}))

    with pytest.raises(nim.NimConfigurationError):
        nim.finish_oauth("code-1", "other")


def test_iter_sse_json_parses_event_stream():
    body = (
        "event: message\n"
        'data: {"jsonrpc": "2.0", "id": 1, "result": {"ok": true}}\n'
        "\n"
        "data: not json\n"
        "\n"
        'data: {"jsonrpc": "2.0", "id": 2,\n'
        'data:  "result": {"second": true}}\n'
        "\n"
    )
    messages = list(nim._iter_sse_json(body))
    assert messages[0]["id"] == 1
    assert messages[1]["result"]["second"] is True


def test_call_tool_prefers_structured_content(monkeypatch):
    session = nim._McpSession.__new__(nim._McpSession)
    session._next_id = 0
    monkeypatch.setattr(
        nim._McpSession, "_post",
        lambda self, payload, timeout=120: {
            "structuredContent": {"workflowId": "wf-1"},
            "content": [{"type": "text", "text": "ignored"}],
        },
    )
    result = session.call_tool("generate_video", {})
    assert result == {"workflowId": "wf-1"}


def test_call_tool_falls_back_to_text_json(monkeypatch):
    session = nim._McpSession.__new__(nim._McpSession)
    session._next_id = 0
    monkeypatch.setattr(
        nim._McpSession, "_post",
        lambda self, payload, timeout=120: {
            "content": [{"type": "text", "text": '{"promptId": "p-1"}'}],
        },
    )
    assert session.call_tool("generate_video", {}) == {"promptId": "p-1"}


def test_credits_route_renders_balance(monkeypatch):
    import asyncio

    from mrp.admin.routes import nim as nim_routes

    monkeypatch.setattr(nim_routes, "get_repo_root", lambda: None)
    monkeypatch.setattr(nim_routes.nim, "credit_balance", lambda repo=None: {
        "totalAvailableCredits": 7758,
        "subscriptionCredits": {"count": 7758, "max": 8000},
    })
    response = asyncio.run(nim_routes.credits(None))
    body = response.body.decode()
    assert "7,758 / 8,000 credits" in body
    assert "badge-live" in body


def test_credits_route_prompts_for_auth(monkeypatch):
    import asyncio

    from mrp.admin.routes import nim as nim_routes

    def raise_auth(repo=None):
        raise nim_routes.nim.NimAuthRequiredError()

    monkeypatch.setattr(nim_routes, "get_repo_root", lambda: None)
    monkeypatch.setattr(nim_routes.nim, "credit_balance", raise_auth)
    response = asyncio.run(nim_routes.credits(None))
    assert "not connected" in response.body.decode()


def test_generate_animated_cover_requires_nim_token(tmp_path, monkeypatch):
    monkeypatch.setenv("MRP_STATE_DIR", str(tmp_path / "state"))

    with pytest.raises(nim.NimAuthRequiredError):
        nim.generate_animated_cover_visual(
            repo=tmp_path,
            cover=tmp_path / "cover.jpg",
            output=tmp_path / "out.mp4",
            prompt="animate the cover",
        )


def test_run_promo_kit_animated_cover_updates_manifest(tmp_path, monkeypatch):
    repo = tmp_path
    (repo / "content" / "releases").mkdir(parents=True)
    (repo / "content" / "artists").mkdir(parents=True)
    (repo / "site" / "public" / "assets" / "releases" / "demo").mkdir(parents=True)
    (repo / "site" / "public" / "samples").mkdir(parents=True)
    kit_dir = repo / "assets" / "processed" / "promo" / "demo"
    kit_dir.mkdir(parents=True)

    (repo / "content" / "releases" / "demo.yaml").write_text(
        "\n".join([
            "release:",
            "  id: demo",
            "  slug: demo",
            "  title: Demo Song",
            "  artist_id: demo-artist",
            "  model: song",
            "  cover_image: site/public/assets/releases/demo/cover.jpg",
            "  song:",
            "    title: Demo Song",
            "    slug: demo-song",
            "    preview_audio: /samples/demo.mp3",
        ])
    )
    (repo / "content" / "artists" / "demo-artist.yaml").write_text(
        "\n".join([
            "artist:",
            "  id: demo-artist",
            "  name: Demo Artist",
            "  promo_blurb: Atmospheric test artist.",
        ])
    )
    (repo / "site" / "public" / "assets" / "releases" / "demo" / "cover.jpg").write_bytes(b"cover")
    (repo / "site" / "public" / "samples" / "demo.mp3").write_bytes(b"audio")
    (kit_dir / "kit.json").write_text(json.dumps({
        "slug": "demo",
        "files": {
            "video": "short.mp4",
            "cover_square": "cover-square.jpg",
            "cover_story": "cover-story.jpg",
        },
    }))

    def fake_generate_animated_cover_visual(**kwargs):
        Path(kwargs["output"]).write_bytes(b"nim visual")
        return {"adapter": "mcp", "model": "Seedance 2 Fast", "model_id": "model-1"}

    def fake_mux(visual, audio, output):
        assert visual.read_bytes() == b"nim visual"
        assert audio.read_bytes() == b"audio"
        output.write_bytes(b"muxed")

    monkeypatch.setattr(nim, "generate_animated_cover_visual", fake_generate_animated_cover_visual)
    monkeypatch.setattr(pipe, "_mux_visual_with_audio", fake_mux)

    result = pipe.run_promo_kit_animated_cover(repo, "demo")

    assert result["ok"] is True
    assert result["video"] == "animated-short.mp4"
    assert (kit_dir / "animated-short.mp4").read_bytes() == b"muxed"
    manifest = json.loads((kit_dir / "kit.json").read_text())
    assert manifest["files"]["animated_video"] == "animated-short.mp4"
    assert manifest["files"]["nim_visual"] == "nim-visual.mp4"
    assert manifest["animated_cover"]["provider"] == "nim"
    assert "No text overlays" in manifest["animated_cover"]["prompt"]
