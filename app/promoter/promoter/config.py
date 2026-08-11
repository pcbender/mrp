import os
from pathlib import Path

from dotenv import load_dotenv

_MRP_ROOT = Path(__file__).resolve().parents[3]
load_dotenv(_MRP_ROOT / ".env")

GOOGLE_API_KEY: str = os.getenv("GOOGLE_SERVICE_API_KEY", "")
ANTHROPIC_API_KEY: str = os.getenv("ANTHROPIC_API_KEY", "")
OPENAI_API_KEY: str = os.getenv("OPENAI_API_KEY", "")

ARTISTS_DIR = _MRP_ROOT / "content" / "artists"
RELEASES_DIR = _MRP_ROOT / "content" / "releases"
CRITIC_OUT_DIR = _MRP_ROOT / "app" / "critic" / "out"

MODEL_DEV = "gemini-2.5-flash"  # 2.0-flash retired by Google (404 as of 2026-07)
MODEL_DEFAULT = "gemini-2.5-pro"

_MODELS = {"dev": MODEL_DEV, "default": MODEL_DEFAULT}


def model_for(tier: str) -> str:
    return _MODELS.get(tier, MODEL_DEFAULT)


# The keyword triumvirate: three vendors vote on the same gated evidence, so a
# single model's invention cannot become a channel keyword on its own.
TRIUMVIRATE = (
    ("gemini", MODEL_DEFAULT),
    ("claude", "claude-opus-5"),
    ("openai", "gpt-5.4"),
)
