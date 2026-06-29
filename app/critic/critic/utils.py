"""Shared text utilities for the critic pipeline."""
from __future__ import annotations


def scrub_emdash(text: str) -> str:
    """Replace em dashes with punctuation that doesn't read as AI-generated."""
    # Spaced em dash ( — ) → comma+space
    text = text.replace(" — ", ", ")
    # Unspaced em dash (—) → regular hyphen
    text = text.replace("—", "-")
    return text
