"""Read access to the reusable actor library, shared by the admin and the
renderer-side workspace.

Kept dependency-light (pydantic + yaml only) so mrp.video modules that run in
the renderer venv can load library actors without importing the admin stack.
The revision hash here is byte-identical to the admin's so pinned
``library_source`` revisions stay stable across both call sites.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

import yaml

from mrp.video.project import ActorConfig, ActorLibraryDocument


def actor_library_path(root: Path) -> Path:
    return root / "assets" / "source" / "video" / "actors"


def actor_revision(actor: ActorConfig) -> str:
    """Stable content hash of a library actor (excludes character/source pin)."""
    payload = actor.model_dump(mode="json", exclude_none=True)
    payload.pop("library_source", None)
    payload.pop("character", None)
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _read_actor(path: Path) -> ActorConfig:
    value: Any = yaml.safe_load(path.read_text(encoding="utf-8"))
    return ActorLibraryDocument.model_validate(value).actor


def load_library_actor(root: Path, actor_id: str) -> ActorConfig | None:
    """Load one library actor by id, or None when it does not exist."""
    path = actor_library_path(root) / f"{actor_id}.yaml"
    if not path.is_file():
        return None
    return _read_actor(path)


def load_library_actors(root: Path) -> list[ActorConfig]:
    directory = actor_library_path(root)
    if not directory.is_dir():
        return []
    return [_read_actor(path) for path in sorted(directory.glob("*.yaml"))]
