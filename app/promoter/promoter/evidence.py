"""
Stage 1 of keyword generation: derive candidate terms from local assets.

Candidates come from the critic records' CLAP tags, aggregated across the
artist's whole catalog. Those tags are unreliable per track — that is why the
critic pipeline doesn't lean on them — but frequency across a catalog inverts
the problem: one stray tag is noise, a tag on 131 of 149 tracks is the artist's
actual sound.

Two gates decide what may be claimed, and a term must clear both:

  rate        appears on at least RATE_FLOOR of the artist's releases. This is
              what stops a single unusual track becoming a claim -- one song
              with bagpipes should not put "Scottish music" on the channel.
  dispersion  appears on at least DISPERSION_FLOOR distinct releases. The rate
              gate alone misses the opposite failure: thirty tracks of one
              concept EP look characteristic by rate but are really one project.

Neither gate can veto. CLAP tags inconsistently -- drums are missing from most
records in a rock catalog -- so presence is evidence and absence means nothing.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from .config import CRITIC_OUT_DIR, RELEASES_DIR

RATE_FLOOR = 0.25
DISPERSION_FLOOR = 3

TAG_KINDS = ("genre", "mood", "instruments")


@dataclass
class Candidate:
    """One term plus the evidence that earned it a place on the ballot."""

    term: str
    kind: str
    tracks: int = 0
    releases: set[str] = field(default_factory=set)
    dates: list[str] = field(default_factory=list)

    def rate(self, total_releases: int) -> float:
        return len(self.releases) / total_releases if total_releases else 0.0

    def evidence(self, total_releases: int) -> str:
        """The one-line justification shown to the models and in --dry-run."""
        span = ""
        dates = sorted(d for d in self.dates if d)
        if dates:
            span = f", {dates[0][:7]}..{dates[-1][:7]}"
            if dates[0][:7] == dates[-1][:7]:
                span = f", {dates[0][:7]}"
        return (
            f"{len(self.releases)}/{total_releases} releases "
            f"({self.rate(total_releases):.0%}), {self.tracks} tracks{span}"
        )


def _load(path: Path) -> dict[str, Any]:
    with path.open(encoding="utf-8") as handle:
        return yaml.safe_load(handle) or {}


def track_release_map(artist_slug: str, releases_dir: Path | None = None) -> tuple[dict[str, str], dict[str, str]]:
    """Map each of the artist's track slugs to its release slug.

    Returns (track_slug -> release_slug, release_slug -> release_date). Critic
    records are named `{artist}--{track_slug}.json`, so this is what lets a
    per-track tag be counted against releases rather than tracks.
    """
    releases_dir = releases_dir or RELEASES_DIR
    tracks: dict[str, str] = {}
    dates: dict[str, str] = {}

    for path in sorted(releases_dir.glob("*.yaml")):
        release = _load(path).get("release") or {}
        if release.get("artist_id") != artist_slug:
            continue
        release_slug = release.get("slug") or path.stem
        dates[release_slug] = release.get("release_date") or ""

        entries = release.get("tracks") or []
        if release.get("song"):
            entries = [release["song"], *entries]
        for entry in entries:
            slug = (entry or {}).get("slug")
            if slug:
                tracks[slug] = release_slug

    return tracks, dates


def gather(
    artist_slug: str,
    critic_dir: Path | None = None,
    releases_dir: Path | None = None,
) -> dict[str, Any]:
    """Collect tag evidence across the artist's catalog.

    Returns a dict with `total_releases`, `matched` (critic records mapped to a
    release), `bpm`, and `candidates` — every term seen, gated or not, so a
    caller can show what fell short of the floors.
    """
    critic_dir = critic_dir or CRITIC_OUT_DIR
    tracks, dates = track_release_map(artist_slug, releases_dir)

    candidates: dict[tuple[str, str], Candidate] = {}
    bpm: list[float] = []
    matched = 0

    for path in sorted(critic_dir.glob(f"{artist_slug}--*.json")):
        track_slug = path.stem[len(artist_slug) + 2 :]
        release_slug = tracks.get(track_slug)
        if not release_slug:
            continue  # a critic record with no live release — not evidence
        matched += 1

        try:
            record = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue

        tempo = (record.get("hard_facts") or {}).get("bpm")
        if isinstance(tempo, (int, float)) and tempo > 0:
            bpm.append(float(tempo))

        tags = record.get("tags") or {}
        for kind in TAG_KINDS:
            for raw in tags.get(kind) or []:
                term = " ".join(str(raw or "").split())
                if not term:
                    continue
                key = (kind, term.casefold())
                candidate = candidates.setdefault(key, Candidate(term=term, kind=kind))
                candidate.tracks += 1
                candidate.releases.add(release_slug)
                candidate.dates.append(dates.get(release_slug, ""))

    ordered = sorted(candidates.values(), key=lambda c: (-len(c.releases), -c.tracks, c.term))
    return {
        "artist_id": artist_slug,
        "total_releases": len(dates),
        "matched": matched,
        "bpm": sorted(bpm),
        "candidates": ordered,
    }


def gated(
    candidates: list[Candidate],
    total_releases: int,
    rate_floor: float = RATE_FLOOR,
    dispersion_floor: int = DISPERSION_FLOOR,
) -> tuple[list[Candidate], list[Candidate]]:
    """Split candidates into (passed, rejected) against both floors."""
    passed: list[Candidate] = []
    rejected: list[Candidate] = []
    for candidate in candidates:
        clears_rate = candidate.rate(total_releases) >= rate_floor
        clears_spread = len(candidate.releases) >= dispersion_floor
        (passed if clears_rate and clears_spread else rejected).append(candidate)
    return passed, rejected


def tempo_terms(bpm: list[float]) -> list[str]:
    """Describe the catalog's tempo in words a listener might actually search.

    Uses the median so a couple of outliers can't rename the catalog, and only
    claims a band the bulk of the catalog actually sits in.
    """
    if not bpm:
        return []
    median = bpm[len(bpm) // 2]
    if median < 90:
        return ["slow tempo"]
    if median < 110:
        return ["midtempo"]
    if median < 140:
        return ["midtempo", "uptempo"]
    return ["uptempo"]


def name_variants(artist_name: str) -> list[str]:
    """Mechanical spellings of the artist's name.

    CLAP cannot hear a spelling, so name forms can't come from tag evidence.
    These are generated crudely on purpose: the per-artist blocklist prunes the
    ones that read wrong, which is cheaper than trying to be clever here.
    """
    name = " ".join(str(artist_name or "").split())
    if not name:
        return []

    out = [name]
    # Split internal capitals: "PCBender" also reads as "PC Bender".
    spaced = ""
    for index, char in enumerate(name):
        if index and char.isupper() and not name[index - 1].isupper() and name[index - 1] != " ":
            spaced += " "
        spaced += char
    if spaced != name:
        out.append(spaced)

    out.extend([f"{name} music", f"{name} official"])

    seen: set[str] = set()
    unique: list[str] = []
    for term in out:
        if term.casefold() not in seen:
            seen.add(term.casefold())
            unique.append(term)
    return unique
