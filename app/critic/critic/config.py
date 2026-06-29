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
GOOGLE_API_KEY: str = os.getenv("GOOGLE_SERVICE_API_KEY", "")

CRITIC_MODEL_DEV: str = "claude-haiku-4-5-20251001"
CRITIC_MODEL_DEFAULT: str = "claude-sonnet-4-6"
CRITIC_MODEL_HERO: str = "claude-opus-4-8"

IMPRESSION_MODEL_DEV: str = "gemini-2.0-flash"
IMPRESSION_MODEL_DEFAULT: str = "gemini-2.5-pro"
IMPRESSION_MODEL_HERO: str = "gemini-3.5-flash"
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
    "gemini-2.0-flash":         "Gemini 2.0 Flash",
    "gemini-2.5-pro":           "Gemini 2.5 Pro",
    "gemini-3.5-flash":         "Gemini 3.5 Flash",
    "HTSAT-tiny":               "HTSAT-tiny",
}


def critic_model_for(tier: str) -> str:
    return _CRITIC_MODELS.get(tier, CRITIC_MODEL_DEV)


def impression_model_for(tier: str) -> str:
    return _IMPRESSION_MODELS.get(tier, IMPRESSION_MODEL_DEFAULT)


def model_label(model_id: str) -> str:
    """Human-friendly model name with ID in parentheses."""
    friendly = _FRIENDLY.get(model_id, model_id)
    if friendly != model_id:
        return f"{friendly} ({model_id})"
    return model_id
