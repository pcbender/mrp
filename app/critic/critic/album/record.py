"""
Album record dataclasses — the Phase 3 contract.

Passes 2 and 3 populate this record. Pass 1 (TrackFinding) is never modified.
"""
from __future__ import annotations

import dataclasses
import json
from dataclasses import dataclass, field


@dataclass
class AlbumFeatures:
    total_runtime_s: float = 0.0
    bpm_curve: list[float] = field(default_factory=list)
    key_progression: list[str] = field(default_factory=list)
    mood_progression: list[str] = field(default_factory=list)
    rank_distribution: dict[str, int] = field(default_factory=dict)
    peak_track: str = ""
    valley_tracks: list[str] = field(default_factory=list)


@dataclass
class CohesionResult:
    palette_consistency: float = 0.0
    theme_threads: list[str] = field(default_factory=list)
    verdict: str = ""  # "cohesive_statement" | "varied" | "shuffle_playlist"


@dataclass
class AlbumVerdictTier:
    rank: int = 2
    label: str = "soft_floor"


@dataclass
class AlbumReview:
    target: str = "album_blurb"
    review_text: str = ""
    verdict_tier: AlbumVerdictTier = field(default_factory=AlbumVerdictTier)
    sum_vs_parts: str = ""   # "greater" | "equal" | "lesser"
    persona_delivery: str = ""  # "on_character" | "expands" | "off_character"
    anchors_used: list[str] = field(default_factory=list)
    status: str = "pending"
    model: str = ""


@dataclass
class TrackInContext:
    track_id: str
    position: int           # 1-based
    standalone_rank: int    # copied from Pass 1, never changed
    context_rank: int | None = None   # null = no rung change
    context_note: str = ""
    review_text: str = ""
    model: str = ""


@dataclass
class AlbumRecord:
    album_id: str                       # "{artist_id}--{release_slug}"
    release_slug: str
    artist: str = ""
    persona: str = ""
    tracklist: list[str] = field(default_factory=list)     # ordered track_ids
    track_records: list[str] = field(default_factory=list) # paths to Pass 1 JSONs
    album_features: AlbumFeatures = field(default_factory=AlbumFeatures)
    cohesion: CohesionResult = field(default_factory=CohesionResult)
    review: AlbumReview = field(default_factory=AlbumReview)
    track_reviews_in_context: list[TrackInContext] = field(default_factory=list)

    def to_json(self, indent: int = 2) -> str:
        return json.dumps(dataclasses.asdict(self), indent=indent, ensure_ascii=False)
