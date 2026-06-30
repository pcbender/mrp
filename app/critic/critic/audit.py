"""
Catalog audit + batch manifest generator.

Walks every content/releases/*.yaml, maps each track to an audio file in the
Masters directory using fuzzy matching, checks whether a critic record already
exists, and writes:
  - a batch manifest JSON ready for `critic batch`
  - a human-readable audit report

Matching strategy (in order):
  1. Exact normalized title match
  2. Normalized base title (strips " - ArtistName" suffix from filename)
  3. Word-subset match (all title words appear in filename)
  4. Fuzzy similarity via difflib (threshold 0.82)
  Ties broken by preferring the file whose suffix matches the track's artist.

Usage:
    python -m critic.audit [--masters-dir /mnt/c/Masters]
                           [--manifest manifests/catalog-YYYY-MM-DD.json]
                           [--report  manifests/audit-YYYY-MM-DD.md]
                           [--force]   # include already-processed tracks
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from datetime import date
from difflib import SequenceMatcher
from enum import Enum
from pathlib import Path

import yaml

_MRP_ROOT = Path(__file__).resolve().parents[3]
_RELEASES_DIR = _MRP_ROOT / "content" / "releases"
_ARTISTS_DIR = _MRP_ROOT / "content" / "artists"
_OUT_DIR = Path(__file__).resolve().parents[1] / "out"
_MANIFESTS_DIR = Path(__file__).resolve().parents[1] / "manifests"

_AUDIO_EXTS = {".wav", ".aif", ".aiff", ".flac"}


class MatchStatus(str, Enum):
    DONE = "done"           # critic record already exists — skip
    EXACT = "exact"         # unambiguous filename match
    FUZZY = "fuzzy"         # close match, probably right
    AMBIGUOUS = "ambiguous" # multiple candidates, needs manual pick
    MISSING = "missing"     # no audio file found


@dataclass
class TrackAudit:
    release_slug: str
    track_slug: str
    artist_slug: str
    track_id: str
    title: str
    release_title: str
    status: MatchStatus
    matched_file: Path | None = None
    candidates: list[Path] = field(default_factory=list)
    match_confidence: str = ""   # "exact" | "base" | "word-subset" | "fuzzy"
    note: str = ""


# ── Normalization ──────────────────────────────────────────────────────────────

def _normalize(s: str) -> str:
    """Lowercase, normalize quotes, strip punctuation, collapse whitespace."""
    s = s.lower()
    # Normalize curly/smart quotes to straight
    s = s.replace("’", "").replace("‘", "").replace("“", "").replace("”", "")
    s = s.replace("'", "").replace('"', "")
    # Remove remaining punctuation except spaces
    s = re.sub(r"[^\w\s]", " ", s)
    return re.sub(r"\s+", " ", s).strip()


def _artist_label(artist_slug: str) -> str:
    """Get display name from artist YAML, falling back to slug."""
    for ext in (".yaml", ".json"):
        p = _ARTISTS_DIR / f"{artist_slug}{ext}"
        if p.exists():
            try:
                data = yaml.safe_load(p.read_text())
                return data.get("artist", {}).get("name", artist_slug)
            except Exception:
                pass
    return artist_slug


# ── Audio index ────────────────────────────────────────────────────────────────

def _build_index(masters_dir: Path) -> dict[str, list[Path]]:
    """
    Returns normalized_key → [Path, ...].
    Each file is indexed twice when it contains " - ":
      "Track Title - ArtistName"  →  index under full stem AND under base title.
    """
    index: dict[str, list[Path]] = {}

    def _add(key: str, path: Path) -> None:
        index.setdefault(key, [])
        if path not in index[key]:
            index[key].append(path)

    for f in masters_dir.rglob("*"):
        if f.suffix.lower() not in _AUDIO_EXTS:
            continue
        stem = f.stem
        _add(_normalize(stem), f)
        if " - " in stem:
            base = stem.rsplit(" - ", 1)[0]
            _add(_normalize(base), f)

    return index


# ── Matching ───────────────────────────────────────────────────────────────────

def _prefer_artist(paths: list[Path], norm_artist: str) -> Path | None:
    """Return the single path whose stem contains the artist label, or None."""
    if not norm_artist:
        return None
    matches = [p for p in paths if norm_artist in _normalize(p.stem)]
    return matches[0] if len(matches) == 1 else None


def _match(title: str, artist_slug: str, index: dict[str, list[Path]]) -> tuple[
    Path | None, list[Path], str
]:
    """
    Returns (matched_path, all_candidates, confidence_label).
    matched_path is None when ambiguous or not found.
    """
    norm = _normalize(title)
    norm_artist = _normalize(_artist_label(artist_slug))

    # 1. Exact normalized match
    if norm in index:
        paths = index[norm]
        if len(paths) == 1:
            return paths[0], paths, "exact"
        preferred = _prefer_artist(paths, norm_artist)
        if preferred:
            return preferred, paths, "exact"
        return None, paths, "exact"   # ambiguous

    # 2. Word-subset: every word in the title appears in the filename stem
    title_words = set(norm.split())
    if title_words:
        subset_hits: list[Path] = []
        for key, paths in index.items():
            if title_words.issubset(set(key.split())):
                subset_hits.extend(p for p in paths if p not in subset_hits)
        if subset_hits:
            if len(subset_hits) == 1:
                return subset_hits[0], subset_hits, "word-subset"
            preferred = _prefer_artist(subset_hits, norm_artist)
            if preferred:
                return preferred, subset_hits, "word-subset"
            return None, subset_hits, "word-subset"

    # 3. Fuzzy similarity
    best_score, best_key = 0.0, ""
    for key in index:
        score = SequenceMatcher(None, norm, key).ratio()
        if score > best_score:
            best_score, best_key = score, key
    if best_score >= 0.82 and best_key:
        paths = index[best_key]
        if len(paths) == 1:
            return paths[0], paths, f"fuzzy({best_score:.2f})"
        preferred = _prefer_artist(paths, norm_artist)
        if preferred:
            return preferred, paths, f"fuzzy({best_score:.2f})"
        return None, paths, f"fuzzy({best_score:.2f})"

    return None, [], ""


# ── Catalog walk ───────────────────────────────────────────────────────────────

def _enumerate_catalog() -> list[dict]:
    """
    Yield one dict per track: release_slug, track_slug, artist_slug, title, release_title.
    Covers singles (model=song) and multi-track releases.
    """
    entries: list[dict] = []
    for p in sorted(_RELEASES_DIR.glob("*.yaml")):
        try:
            data = yaml.safe_load(p.read_text())
        except Exception:
            continue
        rel = data.get("release", {})
        release_slug = p.stem
        artist_slug = rel.get("artist_id", "")
        release_title = rel.get("title", release_slug)

        tracks = rel.get("tracks", [])
        if tracks:
            for t in sorted(tracks, key=lambda t: t.get("number", 0)):
                entries.append(dict(
                    release_slug=release_slug,
                    track_slug=t.get("slug", ""),
                    artist_slug=artist_slug,
                    title=t.get("title", t.get("slug", "")),
                    release_title=release_title,
                ))
        else:
            song = rel.get("song", {})
            if song:
                entries.append(dict(
                    release_slug=release_slug,
                    track_slug=song.get("slug", release_slug),
                    artist_slug=artist_slug,
                    title=song.get("title", rel.get("title", release_slug)),
                    release_title=release_title,
                ))
    return entries


# ── Main audit ─────────────────────────────────────────────────────────────────

def run_audit(
    masters_dir: Path,
    out_dir: Path | None = None,
    force: bool = False,
) -> list[TrackAudit]:
    """
    Audit the catalog against masters_dir. Returns a list of TrackAudit.
    force=True includes already-processed tracks in the manifest.
    """
    out_dir = out_dir or _OUT_DIR
    index = _build_index(masters_dir)
    entries = _enumerate_catalog()
    results: list[TrackAudit] = []

    for e in entries:
        artist_slug = e["artist_slug"]
        track_slug = e["track_slug"]
        release_slug = e["release_slug"]
        track_id = f"{artist_slug}--{track_slug}" if artist_slug else track_slug

        # Already processed?
        record_exists = (out_dir / f"{track_id}.json").exists()
        if record_exists and not force:
            results.append(TrackAudit(
                release_slug=release_slug,
                track_slug=track_slug,
                artist_slug=artist_slug,
                track_id=track_id,
                title=e["title"],
                release_title=e["release_title"],
                status=MatchStatus.DONE,
            ))
            continue

        matched, candidates, confidence = _match(e["title"], artist_slug, index)

        if not candidates:
            status = MatchStatus.MISSING
        elif matched is None:
            status = MatchStatus.AMBIGUOUS
        elif "fuzzy" in confidence:
            status = MatchStatus.FUZZY
        else:
            status = MatchStatus.EXACT

        results.append(TrackAudit(
            release_slug=release_slug,
            track_slug=track_slug,
            artist_slug=artist_slug,
            track_id=track_id,
            title=e["title"],
            release_title=e["release_title"],
            status=status,
            matched_file=matched,
            candidates=candidates,
            match_confidence=confidence,
        ))

    return results


# ── Manifest + report writers ──────────────────────────────────────────────────

def build_manifest(results: list[TrackAudit]) -> list[dict]:
    """Return batch manifest entries for EXACT and FUZZY matched tracks."""
    entries = []
    for r in results:
        if r.status in (MatchStatus.EXACT, MatchStatus.FUZZY) and r.matched_file:
            entries.append({
                "audio": str(r.matched_file),
                "release_slug": r.release_slug,
                "track_slug": r.track_slug,
                "artist_slug": r.artist_slug,
                "target": "blurb",
            })
    return entries


def write_report(
    results: list[TrackAudit],
    manifest: list[dict],
    report_path: Path,
    manifest_path: Path,
) -> None:
    counts = {s: sum(1 for r in results if r.status == s) for s in MatchStatus}
    total = len(results)

    lines = [
        "# MRP Critic — Catalog Audit",
        "",
        f"_Generated {date.today()}  |  Masters: scanned for audio files_",
        "",
        "## Summary",
        "",
        f"| Status | Count |",
        f"|--------|-------|",
        f"| Done (already processed) | {counts[MatchStatus.DONE]} |",
        f"| Matched — exact | {counts[MatchStatus.EXACT]} |",
        f"| Matched — fuzzy | {counts[MatchStatus.FUZZY]} |",
        f"| Ambiguous (multiple candidates) | {counts[MatchStatus.AMBIGUOUS]} |",
        f"| Missing (no audio found) | {counts[MatchStatus.MISSING]} |",
        f"| **Total catalog tracks** | **{total}** |",
        "",
        f"Manifest written to: `{manifest_path}`  ({len(manifest)} tracks ready to batch)",
        "",
    ]

    # Done
    done = [r for r in results if r.status == MatchStatus.DONE]
    if done:
        lines += ["## Already Processed (skipped)", ""]
        for r in done:
            lines.append(f"- `{r.track_id}`")
        lines.append("")

    # Exact matches
    exact = [r for r in results if r.status == MatchStatus.EXACT]
    if exact:
        lines += ["## Exact Matches", ""]
        for r in exact:
            lines.append(f"- `{r.track_id}` → `{r.matched_file.name}`")
        lines.append("")

    # Fuzzy matches
    fuzzy = [r for r in results if r.status == MatchStatus.FUZZY]
    if fuzzy:
        lines += [
            "## Fuzzy Matches (verify before running)",
            "",
            "_These matched by similarity. Confirm the file is correct._",
            "",
        ]
        for r in fuzzy:
            lines.append(
                f"- `{r.track_id}` ({r.match_confidence}) → `{r.matched_file.name}`"
            )
        lines.append("")

    # Ambiguous
    ambiguous = [r for r in results if r.status == MatchStatus.AMBIGUOUS]
    if ambiguous:
        lines += [
            "## Ambiguous — Multiple Candidates",
            "",
            "_Manually add the correct file path to the manifest._",
            "",
        ]
        for r in ambiguous:
            lines.append(f"- `{r.track_id}` ({r.match_confidence})")
            for c in r.candidates:
                lines.append(f"  - `{c}`")
        lines.append("")

    # Missing
    missing = [r for r in results if r.status == MatchStatus.MISSING]
    if missing:
        lines += ["## Missing — No Audio File Found", ""]
        for r in missing:
            lines.append(f"- `{r.track_id}` (title: \"{r.title}\")")
        lines.append("")

    report_path.write_text("\n".join(lines))


# ── CLI ────────────────────────────────────────────────────────────────────────

def _main() -> None:
    import argparse

    today = date.today().isoformat()
    _MANIFESTS_DIR.mkdir(parents=True, exist_ok=True)

    parser = argparse.ArgumentParser(description="MRP Critic — catalog audit + manifest generator")
    parser.add_argument(
        "--masters-dir",
        default="/mnt/c/Masters",
        help="Root directory containing audio master files (default: /mnt/c/Masters)",
    )
    parser.add_argument(
        "--manifest",
        default=str(_MANIFESTS_DIR / f"catalog-{today}.json"),
        help="Output manifest JSON path",
    )
    parser.add_argument(
        "--report",
        default=str(_MANIFESTS_DIR / f"audit-{today}.md"),
        help="Output audit report markdown path",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Include already-processed tracks in the manifest",
    )
    parser.add_argument(
        "--out",
        help="Critic out/ directory for checking existing records",
    )
    args = parser.parse_args()

    masters_dir = Path(args.masters_dir)
    if not masters_dir.exists():
        print(f"✗  Masters directory not found: {masters_dir}")
        raise SystemExit(1)

    out_dir = Path(args.out) if args.out else _OUT_DIR
    manifest_path = Path(args.manifest)
    report_path = Path(args.report)
    manifest_path.parent.mkdir(parents=True, exist_ok=True)

    print(f"Scanning catalog…")
    results = run_audit(masters_dir, out_dir=out_dir, force=args.force)

    manifest = build_manifest(results)
    manifest_path.write_text(json.dumps(manifest, indent=2))

    write_report(results, manifest, report_path, manifest_path)

    # Console summary
    counts = {s: sum(1 for r in results if r.status == s) for s in MatchStatus}
    total = len(results)
    print(f"\n{'─' * 52}")
    print(f"  Catalog Audit — {total} tracks total")
    print(f"{'─' * 52}")
    print(f"  Done (skip)   : {counts[MatchStatus.DONE]}")
    print(f"  Exact match   : {counts[MatchStatus.EXACT]}")
    print(f"  Fuzzy match   : {counts[MatchStatus.FUZZY]}")
    print(f"  Ambiguous     : {counts[MatchStatus.AMBIGUOUS]}")
    print(f"  Missing       : {counts[MatchStatus.MISSING]}")
    print(f"{'─' * 52}")
    print(f"  Manifest      : {manifest_path}  ({len(manifest)} tracks)")
    print(f"  Report        : {report_path}")


if __name__ == "__main__":
    _main()
