"""Shared text utilities for the critic pipeline."""
from __future__ import annotations

import json


def scrub_emdash(text: str) -> str:
    """Replace em dashes with punctuation that doesn't read as AI-generated."""
    # Spaced em dash ( — ) → comma+space
    text = text.replace(" — ", ", ")
    # Unspaced em dash (—) → regular hyphen
    text = text.replace("—", "-")
    return text


def parse_json_response(text: str, required: tuple[str, ...] = ()) -> dict:
    """Extract the JSON object from a model response.

    Models sometimes wrap the object in fences or prose, or emit a draft
    object, comment on it, and then emit a corrected one. Scan every
    top-level object in the text and return the last one that carries all
    ``required`` keys (the model's final answer). Raises ValueError if none do.
    """
    text = text.strip()
    decoder = json.JSONDecoder()
    candidates: list[dict] = []
    pos = text.find("{")
    while pos != -1:
        try:
            obj, end = decoder.raw_decode(text, pos)
        except json.JSONDecodeError:
            pos = text.find("{", pos + 1)
            continue
        if isinstance(obj, dict):
            candidates.append(obj)
        pos = text.find("{", end)
    for obj in reversed(candidates):
        if all(k in obj for k in required):
            return obj
    raise ValueError(f"Could not parse JSON from model response:\n{text}")
