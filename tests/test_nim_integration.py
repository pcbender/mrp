import json
import shutil
import subprocess
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

    def fake_canvas(visual, output):
        assert visual.read_bytes() == b"nim visual"
        output.write_bytes(b"canvas")
        return 5.0

    monkeypatch.setattr(nim, "generate_animated_cover_visual", fake_generate_animated_cover_visual)
    monkeypatch.setattr(pipe, "_mux_visual_with_audio", fake_mux)
    monkeypatch.setattr(pipe, "_render_spotify_canvas", fake_canvas)

    result = pipe.run_promo_kit_animated_cover(repo, "demo")

    assert result["ok"] is True
    assert result["video"] == "animated-short.mp4"
    assert result["canvas"] == "spotify-canvas.mp4"
    assert (kit_dir / "animated-short.mp4").read_bytes() == b"muxed"
    assert (kit_dir / "spotify-canvas.mp4").read_bytes() == b"canvas"
    manifest = json.loads((kit_dir / "kit.json").read_text())
    assert manifest["files"]["animated_video"] == "animated-short.mp4"
    assert manifest["files"]["nim_visual"] == "nim-visual.mp4"
    assert manifest["files"]["spotify_canvas"] == "spotify-canvas.mp4"
    assert manifest["animated_cover"]["provider"] == "nim"
    assert manifest["animated_cover"]["canvas_seconds"] == 5.0
    assert "No text overlays" in manifest["animated_cover"]["prompt"]


def test_render_spotify_canvas_clamps_into_the_three_to_eight_window(tmp_path):
    if not (shutil.which("ffmpeg") and shutil.which("ffprobe")):
        pytest.skip("ffmpeg/ffprobe not on PATH")

    def synth(name: str, seconds: float) -> Path:
        path = tmp_path / name
        subprocess.run(
            ["ffmpeg", "-y", "-f", "lavfi", "-i",
             f"testsrc=size=720x1280:rate=30:duration={seconds}",
             "-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p", str(path)],
            capture_output=True, check=True,
        )
        return path

    # 5s Nim default passes through untouched.
    out = tmp_path / "canvas-5.mp4"
    assert pipe._render_spotify_canvas(synth("src-5.mp4", 5), out) == pytest.approx(5.0, abs=0.1)
    assert pipe._probe_duration(out) == pytest.approx(5.0, abs=0.2)

    # Longer than the Canvas ceiling gets trimmed to 8s.
    out = tmp_path / "canvas-12.mp4"
    assert pipe._render_spotify_canvas(synth("src-12.mp4", 12), out) == pytest.approx(8.0, abs=0.1)
    assert pipe._probe_duration(out) == pytest.approx(8.0, abs=0.2)

    # Shorter than the floor repeats whole loops up past 3s.
    out = tmp_path / "canvas-2.mp4"
    assert pipe._render_spotify_canvas(synth("src-2.mp4", 2), out) == pytest.approx(4.0, abs=0.1)
    assert pipe._probe_duration(out) == pytest.approx(4.0, abs=0.2)

    # Canvas carries no audio track.
    streams = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "stream=codec_type",
         "-of", "default=noprint_wrappers=1:nokey=1", str(out)],
        capture_output=True, text=True,
    ).stdout.split()
    assert streams == ["video"]


# --- identity image generation ------------------------------------------------

def test_workflow_refs_batch_list_and_fallbacks():
    batch = {"workflows": [{"workflowId": "wf-1", "promptId": "p-1"},
                           {"workflowId": "wf-2", "promptId": "p-2"}]}
    assert nim._workflow_refs(batch) == [("wf-1", "p-1"), ("wf-2", "p-2")]
    plural = {"workflowIds": ["wf-1", "wf-2"]}
    assert nim._workflow_refs(plural) == [("wf-1", None), ("wf-2", None)]
    single = {"workflowId": "wf-9", "promptId": "p-9"}
    assert nim._workflow_refs(single) == [("wf-9", "p-9")]
    assert nim._workflow_refs({"status": "queued"}) == []


def test_candidate_name_keeps_guid_basename():
    url = "https://media.nim.video/gen/0b7e5c9a-1f.png?sig=abc%2F123"
    assert nim._candidate_name(url, "wf-1", 0) == "0b7e5c9a-1f.png"
    # No usable extension in the URL -> fall back to the workflow id.
    assert nim._candidate_name("https://media.nim.video/gen/blob", "wf 1!", 2) == "wf1.png"
    assert nim._candidate_name("https://media.nim.video/gen/blob", None, 2) == "candidate-2.png"


class _FakeIdentitySession:
    """Stands in for _McpSession in generate_identity_image tests."""

    calls: list[tuple[str, dict]] = []
    generate_result: dict = {}

    def __init__(self, url, token):
        pass

    def initialize(self):
        pass

    def call_tool(self, name, args, timeout=120):
        type(self).calls.append((name, args))
        return type(self).generate_result


def test_generate_identity_image_batch_downloads_all(tmp_path, monkeypatch):
    refs = []
    for name in ("a.jpg", "b.jpg"):
        ref = tmp_path / name
        ref.write_bytes(b"ref")
        refs.append(ref)

    _FakeIdentitySession.calls = []
    _FakeIdentitySession.generate_result = {
        "workflows": [{"workflowId": "wf-1", "promptId": "p-1"},
                      {"workflowId": "wf-2", "promptId": "p-2"}]}
    monkeypatch.setattr(nim, "_access_token", lambda: "tok")
    monkeypatch.setattr(nim, "_McpSession", _FakeIdentitySession)
    monkeypatch.setattr(nim, "_upload_image", lambda session, path: f"https://files.nim/{path.name}")
    monkeypatch.setattr(nim, "_poll_media_url",
                        lambda session, wid, pid, **kw: f"https://media.nim/{wid}-0af3.png")

    def fake_download(url, output):
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_bytes(b"img")

    monkeypatch.setattr(nim, "_download", fake_download)

    result = nim.generate_identity_image(
        repo=tmp_path, references=refs, output_dir=tmp_path / "cand",
        prompt="new wardrobe", count=2)

    (name, args), = [c for c in _FakeIdentitySession.calls if c[0] == "generate_image"]
    assert args["fileInputs"] == ["https://files.nim/a.jpg", "https://files.nim/b.jpg"]
    assert args["batchSize"] == 2
    assert args["requestedAspectRatio"] == "1:1"
    assert args["model_id"] == nim.DEFAULT_IMAGE_MODEL_ID
    assert [c["name"] for c in result["candidates"]] == ["wf-1-0af3.png", "wf-2-0af3.png"]
    for candidate in result["candidates"]:
        assert (tmp_path / "cand" / candidate["name"]).read_bytes() == b"img"


def test_generate_identity_image_validates_inputs(tmp_path):
    ref = tmp_path / "ref.jpg"
    ref.write_bytes(b"ref")
    with pytest.raises(nim.NimGenerationError, match="No reference"):
        nim.generate_identity_image(repo=tmp_path, references=[], output_dir=tmp_path,
                                    prompt="x")
    with pytest.raises(nim.NimGenerationError, match="count must be 1-4"):
        nim.generate_identity_image(repo=tmp_path, references=[ref], output_dir=tmp_path,
                                    prompt="x", count=5)
    with pytest.raises(nim.NimGenerationError, match="not found"):
        nim.generate_identity_image(repo=tmp_path, references=[tmp_path / "nope.jpg"],
                                    output_dir=tmp_path, prompt="x")


def test_generate_identity_image_requires_nim_token(tmp_path, monkeypatch):
    monkeypatch.setenv("MRP_STATE_DIR", str(tmp_path / "state"))
    ref = tmp_path / "ref.jpg"
    ref.write_bytes(b"ref")
    with pytest.raises(nim.NimAuthRequiredError, match="identity images"):
        nim.generate_identity_image(repo=tmp_path, references=[ref],
                                    output_dir=tmp_path / "cand", prompt="x")
