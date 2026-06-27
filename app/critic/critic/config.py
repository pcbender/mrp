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
