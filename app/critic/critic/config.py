import os
from pathlib import Path

from dotenv import load_dotenv

# Walk up: critic/config.py → critic/ → app/critic/ → app/ → mrp/
_MRP_ROOT = Path(__file__).resolve().parents[3]
load_dotenv(_MRP_ROOT / ".env")

MASTERS_DIR = Path.home() / "audio" / "masters"
PROXY_DIR = Path.home() / "audio" / "proxy"
OUT_DIR = Path(__file__).resolve().parents[1] / "out"

ANTHROPIC_API_KEY: str = os.getenv("ANTHROPIC_API_KEY", "")
# Gemini requires its own AI Studio key; the shared GOOGLE_SERVICE_API_KEY
# (YouTube Data API) is no longer accepted by generativelanguage.googleapis.com.
GEMINI_API_KEY: str = os.getenv("GOOGLE_GEMINI_API_KEY", "")

CRITIC_MODEL_DEV: str = "claude-haiku-4-5-20251001"
CRITIC_MODEL_DEFAULT: str = "claude-sonnet-4-6"
CRITIC_MODEL_HERO: str = "claude-opus-4-8"

# Google's rolling tier aliases (lite / flash / pro mirrors the Claude ladder
# above). The API moves them as models are released and retired, so nothing
# here goes stale; the record stores the concrete model each response reports
# as `model_version`, never the alias.
IMPRESSION_MODEL_DEV: str = "gemini-flash-lite-latest"
IMPRESSION_MODEL_DEFAULT: str = "gemini-flash-latest"
IMPRESSION_MODEL_HERO: str = "gemini-pro-latest"
IMPRESSION_MODEL: str = IMPRESSION_MODEL_DEFAULT  # backward-compat default

CLAP_MODEL: str = "HTSAT-tiny"

_CRITIC_MODELS: dict[str, str] = {
    "dev":     CRITIC_MODEL_DEV,
    "default": CRITIC_MODEL_DEFAULT,
    "hero":    CRITIC_MODEL_HERO,
}
_IMPRESSION_MODELS: dict[str, str] = {
    "dev":     IMPRESSION_MODEL_DEV,
    "default": IMPRESSION_MODEL_DEFAULT,
    "hero":    IMPRESSION_MODEL_HERO,
}

_FRIENDLY: dict[str, str] = {
    "claude-haiku-4-5-20251001": "Haiku 4.5",
    "claude-sonnet-4-6":        "Sonnet 4.6",
    "claude-opus-4-8":          "Opus 4.8",
    "HTSAT-tiny":               "HTSAT-tiny",
}


def critic_model_for(tier: str) -> str:
    return _CRITIC_MODELS.get(tier, CRITIC_MODEL_DEV)


def impression_model_for(tier: str) -> str:
    return _IMPRESSION_MODELS.get(tier, IMPRESSION_MODEL_DEFAULT)


def _gemini_friendly(model_id: str) -> str | None:
    """'gemini-3.8-flash' -> 'Gemini 3.8 Flash'. Records hold whatever concrete
    model the `-latest` alias resolved to, so the label is derived, not tabled."""
    if not model_id.startswith("gemini-"):
        return None
    words = [w if w[:1].isdigit() else w.capitalize() for w in model_id.split("-")]
    return " ".join(words)


def model_label(model_id: str) -> str:
    """Human-friendly model name with ID in parentheses."""
    friendly = _FRIENDLY.get(model_id) or _gemini_friendly(model_id) or model_id
    if friendly != model_id:
        return f"{friendly} ({model_id})"
    return model_id


def gemini_client():
    """Gemini client with a retry policy for the 429/503 capacity errors the
    Generative Language API throws under load (the SDK default never retries)."""
    from google import genai
    from google.genai import types

    retry = types.HttpRetryOptions(attempts=6, initial_delay=2.0, max_delay=15.0)
    return genai.Client(
        api_key=GEMINI_API_KEY,
        http_options=types.HttpOptions(retry_options=retry),
    )
