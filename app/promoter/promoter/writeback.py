"""
Write promoter output back to artist YAML/JSON files.
"""
from __future__ import annotations

import json
from pathlib import Path

import yaml

from .config import ARTISTS_DIR


def _artist_path(slug: str) -> tuple[Path, str]:
    """Return (path, format) for the artist file."""
    for ext, fmt in ((".yaml", "yaml"), (".json", "json")):
        p = ARTISTS_DIR / f"{slug}{ext}"
        if p.exists():
            return p, fmt
    raise FileNotFoundError(f"No artist file found for slug '{slug}' in {ARTISTS_DIR}")


def write_promo_blurb(artist_slug: str, blurb: str) -> Path:
    """Patch promo_blurb onto the artist record. Returns the file path."""
    path, fmt = _artist_path(artist_slug)

    if fmt == "json":
        data = json.loads(path.read_text(encoding="utf-8"))
        data["artist"]["promo_blurb"] = blurb
        path.write_text(
            json.dumps(data, indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )
    else:
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
        data["artist"]["promo_blurb"] = blurb
        path.write_text(
            yaml.dump(data, allow_unicode=True, default_flow_style=False, sort_keys=False),
            encoding="utf-8",
        )

    return path


def write_bio(
    artist_slug: str,
    bio_short: str,
    bio_long: str,
) -> Path:
    """
    Patch bio_short, bio_long, and bio_auto_generated onto the artist record.
    bio_auto_generated flags this as AI-drafted, pending human curation.
    """
    path, fmt = _artist_path(artist_slug)

    if fmt == "json":
        data = json.loads(path.read_text(encoding="utf-8"))
        data["artist"]["bio_short"] = bio_short
        data["artist"]["bio_long"] = bio_long
        data["artist"]["bio_auto_generated"] = True
        path.write_text(
            json.dumps(data, indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )
    else:
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
        data["artist"]["bio_short"] = bio_short
        data["artist"]["bio_long"] = bio_long
        data["artist"]["bio_auto_generated"] = True
        path.write_text(
            yaml.dump(data, allow_unicode=True, default_flow_style=False, sort_keys=False),
            encoding="utf-8",
        )

    return path
