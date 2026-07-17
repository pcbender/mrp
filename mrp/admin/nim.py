"""Nim integration for generated media (animated promo covers, identity images).

Nim's only programmable surface is its MCP server (https://mcp.nim.video/mcp).
This module is a minimal MCP client over streamable HTTP: OAuth via RFC 9728
protected-resource discovery + RFC 7591 dynamic client registration (no
pre-provisioned client id exists for Nim), then JSON-RPC tools/call for
media_upload -> generate_video/generate_image -> get_generation_status.

MRP keeps token storage, auth UX, prompt construction, and final ffmpeg audio
muxing local and deterministic; Nim only produces the raw media.
"""

from __future__ import annotations

import base64
import hashlib
import json
import os
import re
import secrets
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import urlencode, urlsplit

import requests

from mrp.core.spotify_client import load_dotenv

DEFAULT_MCP_URL = "https://mcp.nim.video/mcp"
DEFAULT_MODEL_ID = "ffe4a89d-239b-4c3b-a24a-545e53ee7bab"
DEFAULT_MODEL_NAME = "Seedance 2 Fast"
DEFAULT_MODEL_DURATION_MS = 5000
DEFAULT_MODEL_RESOLUTION = "720p"
DEFAULT_MODEL_ASPECT = "9:16"
# Seedance 2 Fast, 5 s @ 720p (30 credits/s per Nim's price estimate)
DEFAULT_MODEL_CREDITS = 150

# Identity refresh images: Nano Banana Pro Edit — Nim's model for edits that
# must preserve facial identity/likeness across multi-reference composites.
DEFAULT_IMAGE_MODEL_ID = "3c1b1c5b-c1d6-44a8-b986-3068820f4927"
DEFAULT_IMAGE_MODEL_NAME = "Nano Banana Pro Edit"
DEFAULT_IMAGE_MODEL_ASPECT = "1:1"
DEFAULT_IMAGE_MODEL_RESOLUTION = "2K"
# total per image @ 2K per Nim's price estimate
DEFAULT_IMAGE_MODEL_CREDITS = 23
MAX_IMAGE_BATCH = 4
MAX_IMAGE_REFERENCES = 8  # generate_image fileInputs cap

PROTOCOL_VERSION = "2025-06-18"
# Cloudflare fronts mcp.nim.video and rejects default Python UAs (error 1010)
USER_AGENT = "mrp-admin/0.1"


class NimAuthRequiredError(RuntimeError):
    def __init__(self, message: str = "Connect Nim before generating an animated cover.") -> None:
        super().__init__(message)

    def job_output(self) -> dict[str, Any]:
        return {
            "status": "auth_required",
            "service": "nim",
            "message": str(self),
        }


class NimConfigurationError(RuntimeError):
    pass


class NimGenerationError(RuntimeError):
    pass


def config_dir() -> Path:
    root = Path(os.environ.get("MRP_STATE_DIR", Path.home() / ".mrp"))
    root.mkdir(parents=True, exist_ok=True)
    return root


def token_path() -> Path:
    return config_dir() / "nim-token.json"


def client_path() -> Path:
    return config_dir() / "nim-client.json"


def pending_oauth_path() -> Path:
    return config_dir() / "nim-oauth.json"


def _load_env(repo: Path | None = None) -> dict[str, str]:
    merged = dict(os.environ)
    if repo is not None:
        for key, value in load_dotenv(Path(repo) / ".env").items():
            merged.setdefault(key, value)
    return merged


def mcp_url(repo: Path | None = None) -> str:
    return _load_env(repo).get("NIM_MCP_URL", DEFAULT_MCP_URL)


def _b64url(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")


def _json_load(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text())
    except (OSError, ValueError):
        return {}


def _json_write(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2))
    path.chmod(0o600)


def _token_is_current(token: dict[str, Any]) -> bool:
    access_token = token.get("access_token")
    expires_at = token.get("expires_at")
    if not access_token:
        return False
    if expires_at is None:
        return True
    try:
        return float(expires_at) > time.time() + 60
    except (TypeError, ValueError):
        return True


def connected() -> bool:
    return _token_is_current(_json_load(token_path()))


def auth_required_output() -> dict[str, Any]:
    return NimAuthRequiredError().job_output()


# --- OAuth: discovery + dynamic client registration ---------------------------

@dataclass(frozen=True)
class OAuthEndpoints:
    resource: str
    authorize_url: str
    token_url: str
    registration_url: str | None


def _get_json(url: str, timeout: int = 20) -> dict[str, Any] | None:
    try:
        response = requests.get(url, headers={"User-Agent": USER_AGENT}, timeout=timeout)
    except requests.RequestException:
        return None
    if response.status_code >= 400:
        return None
    try:
        data = response.json()
    except ValueError:
        return None
    return data if isinstance(data, dict) else None


def discover(server_url: str) -> OAuthEndpoints:
    parts = urlsplit(server_url)
    origin = f"{parts.scheme}://{parts.netloc}"
    prm = None
    for candidate in (
        f"{origin}/.well-known/oauth-protected-resource{parts.path}",
        f"{origin}/.well-known/oauth-protected-resource",
    ):
        prm = _get_json(candidate)
        if prm:
            break
    prm = prm or {}
    servers = prm.get("authorization_servers") or [origin]
    issuer = str(servers[0]).rstrip("/")
    meta = None
    for candidate in (
        f"{issuer}/.well-known/oauth-authorization-server",
        f"{issuer}/.well-known/openid-configuration",
    ):
        meta = _get_json(candidate)
        if meta and meta.get("authorization_endpoint"):
            break
    if not meta or not meta.get("authorization_endpoint") or not meta.get("token_endpoint"):
        raise NimConfigurationError(f"Could not discover OAuth endpoints for {server_url}.")
    return OAuthEndpoints(
        resource=str(prm.get("resource") or server_url),
        authorize_url=str(meta["authorization_endpoint"]),
        token_url=str(meta["token_endpoint"]),
        registration_url=str(meta["registration_endpoint"]) if meta.get("registration_endpoint") else None,
    )


def _ensure_client(endpoints: OAuthEndpoints, redirect_uri: str) -> str:
    stored = _json_load(client_path())
    if stored.get("client_id") and redirect_uri in (stored.get("redirect_uris") or []):
        return str(stored["client_id"])
    if not endpoints.registration_url:
        raise NimConfigurationError("Nim's OAuth server does not offer dynamic client registration.")
    redirect_uris = sorted({*(stored.get("redirect_uris") or []), redirect_uri})
    response = requests.post(
        endpoints.registration_url,
        json={
            "client_name": "MRP Admin",
            "redirect_uris": redirect_uris,
            "grant_types": ["authorization_code"],
            "response_types": ["code"],
            "token_endpoint_auth_method": "none",
        },
        headers={"User-Agent": USER_AGENT},
        timeout=30,
    )
    if response.status_code >= 400:
        raise NimConfigurationError(f"Nim client registration failed ({response.status_code}).")
    registration = response.json()
    if not registration.get("client_id"):
        raise NimConfigurationError("Nim client registration returned no client_id.")
    _json_write(client_path(), registration)
    return str(registration["client_id"])


def begin_oauth(repo: Path | None, public_base_url: str, return_to: str) -> str:
    server_url = mcp_url(repo)
    endpoints = discover(server_url)
    redirect_uri = _load_env(repo).get("NIM_REDIRECT_URI") or f"{public_base_url.rstrip('/')}/nim/oauth/callback"
    client_id = _ensure_client(endpoints, redirect_uri)
    verifier = secrets.token_urlsafe(48)
    challenge = _b64url(hashlib.sha256(verifier.encode("ascii")).digest())
    state = secrets.token_urlsafe(24)
    _json_write(pending_oauth_path(), {
        "state": state,
        "code_verifier": verifier,
        "return_to": return_to or "/releases",
        "created_at": int(time.time()),
        "redirect_uri": redirect_uri,
        "client_id": client_id,
        "token_url": endpoints.token_url,
        "resource": endpoints.resource,
    })
    return endpoints.authorize_url + "?" + urlencode({
        "response_type": "code",
        "client_id": client_id,
        "redirect_uri": redirect_uri,
        "state": state,
        "code_challenge": challenge,
        "code_challenge_method": "S256",
        "resource": endpoints.resource,
    })


def finish_oauth(code: str, state: str) -> str:
    pending = _json_load(pending_oauth_path())
    if not pending or pending.get("state") != state:
        raise NimConfigurationError("Nim OAuth state did not match. Start Connect Nim again.")
    token_url = str(pending.get("token_url") or "")
    if not token_url:
        raise NimConfigurationError("Nim OAuth session is incomplete. Start Connect Nim again.")
    response = requests.post(
        token_url,
        data={
            "grant_type": "authorization_code",
            "client_id": str(pending.get("client_id") or ""),
            "code": code,
            "redirect_uri": str(pending.get("redirect_uri") or ""),
            "code_verifier": str(pending.get("code_verifier") or ""),
            "resource": str(pending.get("resource") or ""),
        },
        headers={"User-Agent": USER_AGENT},
        timeout=30,
    )
    if response.status_code >= 400:
        raise NimConfigurationError(f"Nim token exchange failed ({response.status_code}).")
    token = response.json()
    if token.get("expires_in") is not None:
        try:
            token["expires_at"] = int(time.time()) + int(token["expires_in"])
        except (TypeError, ValueError):
            pass
    # kept for refresh attempts, should Nim ever issue refresh tokens
    token["token_url"] = token_url
    token["client_id"] = pending.get("client_id")
    token["resource"] = pending.get("resource")
    _json_write(token_path(), token)
    try:
        pending_oauth_path().unlink()
    except FileNotFoundError:
        pass
    return str(pending.get("return_to") or "/releases")


def _refresh(token: dict[str, Any]) -> str | None:
    refresh_token = token.get("refresh_token")
    token_url = token.get("token_url")
    client_id = token.get("client_id")
    if not (refresh_token and token_url and client_id):
        return None
    try:
        response = requests.post(
            str(token_url),
            data={
                "grant_type": "refresh_token",
                "refresh_token": str(refresh_token),
                "client_id": str(client_id),
                "resource": str(token.get("resource") or ""),
            },
            headers={"User-Agent": USER_AGENT},
            timeout=30,
        )
    except requests.RequestException:
        return None
    if response.status_code >= 400:
        return None
    fresh = response.json()
    if not fresh.get("access_token"):
        return None
    if fresh.get("expires_in") is not None:
        try:
            fresh["expires_at"] = int(time.time()) + int(fresh["expires_in"])
        except (TypeError, ValueError):
            pass
    fresh.setdefault("refresh_token", refresh_token)
    fresh["token_url"] = token_url
    fresh["client_id"] = client_id
    fresh["resource"] = token.get("resource")
    _json_write(token_path(), fresh)
    return str(fresh["access_token"])


def _access_token() -> str:
    token = _json_load(token_path())
    if _token_is_current(token):
        return str(token["access_token"])
    refreshed = _refresh(token)
    if refreshed:
        return refreshed
    raise NimAuthRequiredError()


# --- MCP client (streamable HTTP) ---------------------------------------------

def _iter_sse_json(body: str):
    data_lines: list[str] = []
    for line in body.splitlines() + [""]:
        if line.startswith("data:"):
            data_lines.append(line[5:].lstrip())
        elif not line.strip() and data_lines:
            try:
                yield json.loads("\n".join(data_lines))
            except ValueError:
                pass
            data_lines = []


def _result_text(result: dict[str, Any]) -> str:
    parts = []
    for item in result.get("content") or []:
        if isinstance(item, dict) and item.get("type") == "text":
            parts.append(str(item.get("text") or ""))
    return "\n".join(parts)


class _McpSession:
    def __init__(self, url: str, access_token: str) -> None:
        self._url = url
        self._session_id: str | None = None
        self._next_id = 0
        self._http = requests.Session()
        self._http.headers.update({
            "User-Agent": USER_AGENT,
            "Authorization": f"Bearer {access_token}",
            "Accept": "application/json, text/event-stream",
            "MCP-Protocol-Version": PROTOCOL_VERSION,
        })

    def _post(self, payload: dict[str, Any], timeout: int = 120) -> dict[str, Any] | None:
        headers = {"Mcp-Session-Id": self._session_id} if self._session_id else {}
        response = self._http.post(self._url, json=payload, headers=headers, timeout=timeout)
        if response.status_code in (401, 403):
            raise NimAuthRequiredError()
        if response.status_code >= 400:
            raise NimGenerationError(f"Nim MCP request failed ({response.status_code}): {response.text[:200]}")
        session_id = response.headers.get("Mcp-Session-Id") or response.headers.get("mcp-session-id")
        if session_id:
            self._session_id = session_id
        request_id = payload.get("id")
        if request_id is None:  # notification
            return None
        if "text/event-stream" in response.headers.get("Content-Type", ""):
            for message in _iter_sse_json(response.text):
                if message.get("id") == request_id and ("result" in message or "error" in message):
                    return self._unwrap(message)
            raise NimGenerationError("Nim MCP stream ended without a response.")
        return self._unwrap(response.json())

    @staticmethod
    def _unwrap(message: dict[str, Any]) -> dict[str, Any]:
        error = message.get("error")
        if error:
            detail = error.get("message") if isinstance(error, dict) else error
            raise NimGenerationError(f"Nim MCP error: {str(detail)[:300]}")
        result = message.get("result")
        return result if isinstance(result, dict) else {}

    def _rpc(self, method: str, params: dict[str, Any], timeout: int = 120) -> dict[str, Any]:
        self._next_id += 1
        result = self._post(
            {"jsonrpc": "2.0", "id": self._next_id, "method": method, "params": params},
            timeout=timeout,
        )
        return result or {}

    def initialize(self) -> None:
        self._rpc("initialize", {
            "protocolVersion": PROTOCOL_VERSION,
            "capabilities": {},
            "clientInfo": {"name": "mrp-admin", "version": "0.1"},
        })
        self._post({"jsonrpc": "2.0", "method": "notifications/initialized", "params": {}})

    def call_tool(self, name: str, arguments: dict[str, Any], timeout: int = 120) -> dict[str, Any]:
        result = self._rpc("tools/call", {"name": name, "arguments": arguments}, timeout=timeout)
        text = _result_text(result)
        if result.get("isError"):
            raise NimGenerationError(f"Nim {name} failed: {text[:300]}")
        structured = result.get("structuredContent")
        if isinstance(structured, dict):
            return structured
        try:
            parsed = json.loads(text)
        except ValueError:
            return {"text": text}
        return parsed if isinstance(parsed, dict) else {"text": text}


def credit_balance(repo: Path | None = None) -> dict[str, Any]:
    session = _McpSession(mcp_url(repo), _access_token())
    session.initialize()
    return session.call_tool("get_credit_balance", {})


# --- Animated cover generation --------------------------------------------------

def animated_cover_prompt(release: dict[str, Any], artist: dict[str, Any]) -> str:
    title = release.get("title") or "the release"
    artist_name = artist.get("name") or release.get("artist_id") or "the artist"
    blurb = artist.get("promo_blurb") or artist.get("bio_short") or ""
    return (
        f"Animate the album cover for {title} by {artist_name} as a tasteful vertical "
        "social music visual. Preserve the cover art identity and composition, add "
        "subtle cinematic depth, slow parallax, light movement, and atmospheric motion. "
        "No text overlays, no logos, no new people, no lyric subtitles, no hard cuts. "
        f"Artist voice context: {blurb[:700]}"
    )


_IMAGE_TYPES = {".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".png": "image/png",
                ".webp": "image/webp", ".gif": "image/gif"}


def _upload_image(session: _McpSession, cover: Path) -> str:
    result = session.call_tool("media_upload", {})
    upload_url = result.get("upload_url") or result.get("uploadUrl")
    if not upload_url:
        # tool result is a curl example with a signed URL embedded
        blob = str(result.get("curl_example") or result.get("curlExample") or result.get("text") or "")
        match = re.search(r"https://\S+", blob)
        upload_url = match.group(0).rstrip("'\"\\") if match else None
    if not upload_url:
        raise NimGenerationError("Nim media_upload did not return an upload URL.")
    content_type = _IMAGE_TYPES.get(cover.suffix.lower(), "image/jpeg")
    with cover.open("rb") as fh:
        response = requests.post(
            upload_url,
            files={"file": (cover.name, fh, content_type)},
            headers={"User-Agent": USER_AGENT},
            timeout=120,
        )
    if response.status_code >= 400:
        raise NimGenerationError(f"Nim upload failed ({response.status_code}).")
    upload = response.json()
    file_url = upload.get("file_url") or upload.get("fileUrl") or upload.get("url")
    if not file_url:
        raise NimGenerationError("Nim upload response did not include a file URL.")
    return str(file_url)


_MEDIA_KEYS = ("mediaUrl", "media_url", "videoUrl", "video_url",
               "imageUrl", "image_url")


def _find_media_url(obj: Any, keys: tuple[str, ...] = _MEDIA_KEYS) -> str | None:
    if isinstance(obj, dict):
        for key in keys:
            value = obj.get(key)
            if isinstance(value, str) and value.startswith("http"):
                return value
        for value in obj.values():
            found = _find_media_url(value, keys)
            if found:
                return found
    elif isinstance(obj, list):
        for item in obj:
            found = _find_media_url(item, keys)
            if found:
                return found
    return None


def _poll_media_url(session: _McpSession, workflow_id: Any, prompt_id: Any,
                    attempts: int = 90, interval: float = 5.0) -> str:
    args = {key: value for key, value in
            (("workflowId", workflow_id), ("promptId", prompt_id)) if value}
    for attempt in range(attempts):
        status = session.call_tool("get_generation_status", args, timeout=60)
        state = str(status.get("status") or "").lower()
        if state in ("failed", "cancelled", "removed"):
            raise NimGenerationError(f"Nim generation {state}.")
        media_url = _find_media_url(status)
        if media_url:
            return media_url
        if state == "finished":
            raise NimGenerationError("Nim generation finished but returned no media URL.")
        if attempt < attempts - 1:
            time.sleep(interval)
    raise NimGenerationError("Nim generation timed out before returning media.")


def _download(url: str, output: Path) -> None:
    response = requests.get(url, headers={"User-Agent": USER_AGENT}, timeout=300)
    if response.status_code >= 400:
        raise NimGenerationError(f"Nim media download failed ({response.status_code}).")
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_bytes(response.content)


def generate_animated_cover_visual(
    *,
    repo: Path,
    cover: Path,
    output: Path,
    prompt: str,
    model_id: str = DEFAULT_MODEL_ID,
    model_name: str = DEFAULT_MODEL_NAME,
    duration_ms: int = DEFAULT_MODEL_DURATION_MS,
    resolution: str = DEFAULT_MODEL_RESOLUTION,
) -> dict[str, Any]:
    """Generate a silent 9:16 visual bed with Nim via its MCP server."""
    access_token = _access_token()
    session = _McpSession(mcp_url(repo), access_token)
    session.initialize()

    file_url = _upload_image(session, cover)
    generation = session.call_tool("generate_video", {
        "model_id": model_id,
        "model_name": model_name,
        "prompt": prompt,
        "fileInputs": [file_url],
        "requestedAspectRatio": DEFAULT_MODEL_ASPECT,
        "mediaLength": duration_ms,
        "resolution": resolution,
    })
    if generation.get("status") == "insufficient_credits":
        raise NimGenerationError("Nim has insufficient credits — top up at nim.video and rerun.")
    workflow_id = generation.get("workflowId") or generation.get("workflow_id")
    prompt_id = generation.get("promptId") or generation.get("prompt_id")
    if not (workflow_id or prompt_id):
        raise NimGenerationError(
            f"Nim generate_video did not return a workflow id: {str(generation)[:200]}")

    media_url = _poll_media_url(session, workflow_id, prompt_id)
    _download(media_url, output)
    if not output.is_file() or output.stat().st_size == 0:
        raise NimGenerationError("Nim media download produced an empty file.")
    return {
        "adapter": "mcp",
        "model": model_name,
        "model_id": model_id,
        "workflow_id": workflow_id,
        "prompt_id": prompt_id,
    }


def _workflow_refs(generation: dict[str, Any]) -> list[tuple[Any, Any]]:
    """(workflow_id, prompt_id) pairs from a generate_* result.

    batchSize > 1 enqueues one workflow per variation; Nim's response shape
    for the batch list is not pinned down, so accept a list under a few
    plausible keys before falling back to the single-workflow keys.
    """
    refs: list[tuple[Any, Any]] = []
    for key in ("workflows", "generations", "prompts", "items"):
        items = generation.get(key)
        if isinstance(items, list):
            for item in items:
                if isinstance(item, dict):
                    wid = item.get("workflowId") or item.get("workflow_id")
                    pid = item.get("promptId") or item.get("prompt_id")
                    if wid or pid:
                        refs.append((wid, pid))
            if refs:
                return refs
    wids = generation.get("workflowIds") or generation.get("workflow_ids")
    if isinstance(wids, list) and wids:
        return [(wid, None) for wid in wids]
    wid = generation.get("workflowId") or generation.get("workflow_id")
    pid = generation.get("promptId") or generation.get("prompt_id")
    if wid or pid:
        return [(wid, pid)]
    return []


def _candidate_name(media_url: str, fallback: Any, index: int) -> str:
    """Filename for a downloaded candidate — keep Nim's GUID basename when
    the media URL has a usable one, so the archived-in-git copy stays
    traceable to the generation."""
    base = re.sub(r"[^A-Za-z0-9._-]", "", Path(urlsplit(media_url).path).name)
    if base and Path(base).suffix.lower() in _IMAGE_TYPES:
        return base
    stem = re.sub(r"[^A-Za-z0-9._-]", "", str(fallback or ""))
    return f"{stem or f'candidate-{index}'}.png"


def generate_identity_image(
    *,
    repo: Path,
    references: list[Path],
    output_dir: Path,
    prompt: str,
    count: int = 1,
    model_id: str = DEFAULT_IMAGE_MODEL_ID,
    model_name: str = DEFAULT_IMAGE_MODEL_NAME,
    aspect: str = DEFAULT_IMAGE_MODEL_ASPECT,
    resolution: str = DEFAULT_IMAGE_MODEL_RESOLUTION,
) -> dict[str, Any]:
    """Generate likeness-consistent candidate images from reference images.

    Uploads every reference, runs one generate_image call (batchSize=count),
    then polls each variation's workflow and downloads the results into
    output_dir under their Nim GUID basenames. Candidates are staging files —
    the caller decides what, if anything, gets published or archived.
    """
    if not references:
        raise NimGenerationError("No reference images to generate from.")
    if len(references) > MAX_IMAGE_REFERENCES:
        raise NimGenerationError(
            f"Too many reference images ({len(references)} > {MAX_IMAGE_REFERENCES}).")
    missing = [str(ref) for ref in references if not ref.is_file()]
    if missing:
        raise NimGenerationError(f"Reference image not found: {', '.join(missing)}")
    if not 1 <= count <= MAX_IMAGE_BATCH:
        raise NimGenerationError(f"Candidate count must be 1-{MAX_IMAGE_BATCH}.")

    access_token = _access_token()
    session = _McpSession(mcp_url(repo), access_token)
    session.initialize()

    file_urls = [_upload_image(session, ref) for ref in references]
    generation = session.call_tool("generate_image", {
        "model_id": model_id,
        "model_name": model_name,
        "prompt": prompt,
        "fileInputs": file_urls,
        "requestedAspectRatio": aspect,
        "resolution": resolution,
        "batchSize": count,
    })
    if generation.get("status") == "insufficient_credits":
        raise NimGenerationError("Nim has insufficient credits — top up at nim.video and rerun.")
    workflows = _workflow_refs(generation)
    if not workflows:
        raise NimGenerationError(
            f"Nim generate_image did not return a workflow id: {str(generation)[:200]}")

    candidates = []
    for index, (workflow_id, prompt_id) in enumerate(workflows):
        media_url = _poll_media_url(session, workflow_id, prompt_id)
        output = output_dir / _candidate_name(media_url, workflow_id or prompt_id, index)
        _download(media_url, output)
        if not output.is_file() or output.stat().st_size == 0:
            raise NimGenerationError("Nim media download produced an empty file.")
        candidates.append({
            "file": str(output),
            "name": output.name,
            "workflow_id": workflow_id,
            "prompt_id": prompt_id,
        })
    return {
        "adapter": "mcp",
        "model": model_name,
        "model_id": model_id,
        "requested": count,
        "candidates": candidates,
    }
