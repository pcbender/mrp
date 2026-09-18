import os
from pathlib import Path

from dotenv import load_dotenv

_MRP_ROOT = Path(__file__).resolve().parents[3]
load_dotenv(_MRP_ROOT / ".env")

# Gemini requires its own AI Studio key; the shared GOOGLE_SERVICE_API_KEY
# (YouTube Data API) is no longer accepted by generativelanguage.googleapis.com.
GEMINI_API_KEY: str = os.getenv("GOOGLE_GEMINI_API_KEY", "")
ANTHROPIC_API_KEY: str = os.getenv("ANTHROPIC_API_KEY", "")
OPENAI_API_KEY: str = os.getenv("OPENAI_API_KEY", "")

ARTISTS_DIR = _MRP_ROOT / "content" / "artists"
RELEASES_DIR = _MRP_ROOT / "content" / "releases"
CRITIC_OUT_DIR = _MRP_ROOT / "app" / "critic" / "out"

# Google's rolling tier aliases: the API moves them as models are released and
# retired (the pinned 2.x names all 404'd in 2026-09), so nothing here goes
# stale. Every response reports the concrete model it resolved to as
# `model_version`; that is what gets recorded in artifacts, never the alias.
MODEL_DEV = "gemini-flash-lite-latest"
MODEL_DEFAULT = "gemini-pro-latest"

_MODELS = {"dev": MODEL_DEV, "default": MODEL_DEFAULT}


def model_for(tier: str) -> str:
    return _MODELS.get(tier, MODEL_DEFAULT)


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


# The keyword triumvirate: three vendors vote on the same gated evidence, so a
# single model's invention cannot become a channel keyword on its own.
TRIUMVIRATE = (
    ("gemini", MODEL_DEFAULT),
    ("claude", "claude-opus-5"),
    ("openai", "gpt-5.4"),
)
