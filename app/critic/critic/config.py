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
IMPRESSION_MODEL: str = "gemini-2.5-pro"
CLAP_MODEL: str = "HTSAT-tiny"

_FRIENDLY: dict[str, str] = {
    "claude-haiku-4-5-20251001": "Haiku 4.5",
    "claude-sonnet-4-6":        "Sonnet 4.6",
    "claude-opus-4-8":          "Opus 4.8",
    "gemini-2.5-pro":           "Gemini 2.5 Pro",
    "gemini-2.0-flash":         "Gemini 2.0 Flash",
    "HTSAT-tiny":               "HTSAT-tiny",
}


def model_label(model_id: str) -> str:
    """Human-friendly model name with ID in parentheses."""
    friendly = _FRIENDLY.get(model_id, model_id)
    if friendly != model_id:
        return f"{friendly} ({model_id})"
    return model_id
