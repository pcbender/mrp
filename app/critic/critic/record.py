from __future__ import annotations

import dataclasses
import json
from dataclasses import dataclass, field


@dataclass
class SourceRecord:
    type: str   # "local_master" | "landr_redownload"
    path: str
    proxy: str


@dataclass
class Confidence:
    bpm: float = 0.0
    key: float = 0.0


@dataclass
class Section:
    start: float
    end: float
    label: str


@dataclass
class HardFacts:
    bpm: float = 0.0
    key: str = ""
    mode: str = ""
    time_signature: str = ""
    duration_s: float = 0.0
    lufs: float = 0.0
    sections: list[Section] = field(default_factory=list)
    confidence: Confidence = field(default_factory=Confidence)


@dataclass
class Tags:
    genre: list[str] = field(default_factory=list)
    mood: list[str] = field(default_factory=list)
    instruments: list[str] = field(default_factory=list)
    model: str = ""


@dataclass
class Impression:
    text: str = ""
    model: str = ""


@dataclass
class VerdictTier:
    rank: int = 2
    label: str = "soft_floor"


@dataclass
class Review:
    target: str = "blurb"
    review_text: str = ""
    status: str = "pending"
    verdict_tier: VerdictTier = field(default_factory=VerdictTier)
    anchors_used: list[str] = field(default_factory=list)
    model: str = ""


@dataclass
class TrackFinding:
    track_id: str
    source: SourceRecord
    lyrics: str = ""
    persona: str = ""
    hard_facts: HardFacts = field(default_factory=HardFacts)
    tags: Tags = field(default_factory=Tags)
    impression: Impression = field(default_factory=Impression)
    review: Review = field(default_factory=Review)

    def to_json(self, indent: int = 2) -> str:
        return json.dumps(dataclasses.asdict(self), indent=indent, ensure_ascii=False)
