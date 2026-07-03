"""Read/edit critic output records (app/critic/out/*.json) from the admin UI.

The critic apps own these files; the admin edits only the human-reviewable
slices: review_text and review status (pending → approved → publishable).
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

REVIEW_STATUSES = ["pending", "approved", "publishable"]


def out_dir(root: Path) -> Path:
    return root / "app" / "critic" / "out"


def critic_bin(root: Path) -> str:
    return str(root / "app" / "critic" / ".venv" / "bin" / "critic")


def promoter_bin(root: Path) -> str:
    return str(root / "app" / "critic" / ".venv" / "bin" / "promoter")


def track_record_id(artist_id: str, track_slug: str) -> str:
    return f"{artist_id}--{track_slug}"


def album_record_id(artist_id: str, release_slug: str) -> str:
    return f"album--{artist_id}--{release_slug}"


def load_record(root: Path, record_id: str) -> dict[str, Any] | None:
    path = out_dir(root) / f"{record_id}.json"
    if not path.is_file():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (ValueError, OSError):
        return None


def _save_record(root: Path, record_id: str, record: dict) -> None:
    path = out_dir(root) / f"{record_id}.json"
    path.write_text(json.dumps(record, indent=2, ensure_ascii=False), encoding="utf-8")


def update_review(
    root: Path,
    record_id: str,
    review_text: str | None = None,
    status: str | None = None,
) -> dict[str, Any]:
    """Patch review_text and/or status on a track finding or album record."""
    record = load_record(root, record_id)
    if record is None:
        raise ValueError(f"No critic record: {record_id}")
    review = record.setdefault("review", {})
    if review_text is not None:
        review["review_text"] = review_text
    if status is not None:
        if status not in REVIEW_STATUSES:
            raise ValueError(f"Invalid review status: {status}")
        review["status"] = status
    _save_record(root, record_id, record)
    return record


def update_context_review(
    root: Path,
    album_id_: str,
    track_id: str,
    review_text: str,
) -> dict[str, Any]:
    """Edit the Pass-3 contextual review for one track inside an album record."""
    record = load_record(root, album_id_)
    if record is None:
        raise ValueError(f"No album record: {album_id_}")
    for tic in record.get("track_reviews_in_context") or []:
        if tic.get("track_id") == track_id:
            tic["review_text"] = review_text
            _save_record(root, album_id_, record)
            return record
    raise ValueError(f"Track {track_id} not in album record {album_id_}")


def review_summary(record: dict | None) -> dict[str, Any]:
    """Uniform summary of a record's review for the stage page."""
    if not record:
        return {"exists": False, "status": None, "rank": None, "label": None,
                "target": None, "model": None, "review_text": None}
    review = record.get("review") or {}
    tier = review.get("verdict_tier") or {}
    return {
        "exists": True,
        "status": review.get("status") or "pending",
        "rank": tier.get("rank"),
        "label": tier.get("label"),
        "target": review.get("target"),
        "model": review.get("model"),
        "review_text": review.get("review_text") or "",
    }
