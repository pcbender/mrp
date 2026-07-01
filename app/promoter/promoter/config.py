import os
from pathlib import Path

from dotenv import load_dotenv

_MRP_ROOT = Path(__file__).resolve().parents[3]
load_dotenv(_MRP_ROOT / ".env")

GOOGLE_API_KEY: str = os.getenv("GOOGLE_SERVICE_API_KEY", "")

ARTISTS_DIR = _MRP_ROOT / "content" / "artists"
RELEASES_DIR = _MRP_ROOT / "content" / "releases"
CRITIC_OUT_DIR = _MRP_ROOT / "app" / "critic" / "out"

MODEL_DEV = "gemini-2.0-flash"
MODEL_DEFAULT = "gemini-2.5-pro"

_MODELS = {"dev": MODEL_DEV, "default": MODEL_DEFAULT}


def model_for(tier: str) -> str:
    return _MODELS.get(tier, MODEL_DEFAULT)
