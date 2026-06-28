"""
Pipeline review document generator.

Reads existing out/ records and renders a human-readable markdown document
showing every ingredient that produced the finished review — no API calls made.

Usage:
    critic show <id>            auto-detect track or album
    critic show <id> --save     write to out/pipeline_<id>.md
    critic show <id> --save --out <dir>

<id> can be:
    pcbender--apa   track_id  (looks for out/pcbender--apa.json)
    tria            release_slug  (resolves to out/pcbender--tria.json via catalog)
    pcbender--tria  album_id  (direct lookup)
"""
from __future__ import annotations

import argparse
import json
import textwrap
from pathlib import Path

from .catalog import get_release_meta, get_release_tracks
from .config import CLAP_MODEL, OUT_DIR, model_label


def _infer_model(model_id: str) -> str:
    """Return friendly label; if empty/unknown, infer from context where possible."""
    if not model_id or model_id == "unknown":
        return "unknown (predates tracking)"
    return model_label(model_id)


def _infer_tags_model(tags: dict) -> str:
    """Tags model: stored if new record, infer HTSAT-tiny if tags exist but field absent."""
    m = tags.get("model", "")
    if m:
        return model_label(m)
    if tags.get("genre") or tags.get("mood") or tags.get("instruments"):
        return f"{model_label(CLAP_MODEL)} (inferred)"
    return "not run"


# ── Helpers ───────────────────────────────────────────────────────────────────

def _load_json(path: Path) -> dict | None:
    try:
        return json.loads(path.read_text())
    except (FileNotFoundError, json.JSONDecodeError):
        return None


def _resolve(id_: str, out_dir: Path) -> tuple[dict, str]:
    """
    Return (record_dict, mode) where mode is 'track' or 'album'.
    Tries: direct path, release_slug → album, release_slug → single track.
    """
    # Direct lookup
    direct = _load_json(out_dir / f"{id_}.json")
    if direct is not None:
        mode = "album" if "album_id" in direct else "track"
        return direct, mode

    # Try as release_slug → find album record via catalog
    meta = get_release_meta(id_)
    if meta:
        artist_slug = meta["artist_id"]
        album_id = f"{artist_slug}--{id_}"
        album = _load_json(out_dir / f"{album_id}.json")
        if album is not None:
            return album, "album"

    raise FileNotFoundError(
        f"No record found for '{id_}' in {out_dir}.\n"
        f"Expected: {out_dir}/{id_}.json  or album record via release slug."
    )


def _fmt_duration(seconds: float) -> str:
    m, s = divmod(int(seconds), 60)
    return f"{m}:{s:02d}"


def _truncate(text: str, lines: int = 12) -> str:
    all_lines = text.strip().splitlines()
    if len(all_lines) <= lines:
        return text.strip()
    return "\n".join(all_lines[:lines]) + f"\n… ({len(all_lines) - lines} more lines)"


# ── Track pipeline doc ────────────────────────────────────────────────────────

def _track_doc(record: dict, out_dir: Path) -> str:
    track_id = record.get("track_id", "unknown")
    source = record.get("source", {})
    hf = record.get("hard_facts", {})
    imp = record.get("impression", {})
    tags = record.get("tags", {})
    rv = record.get("review", {})
    vt = rv.get("verdict_tier", {})
    conf = hf.get("confidence", {})

    sections = hf.get("sections", [])
    section_str = ", ".join(
        f"{s.get('label', '?')} {_fmt_duration(s.get('start', 0))}–{_fmt_duration(s.get('end', 0))}"
        for s in sections
    ) or "n/a"

    # Model provenance
    imp_model = imp.get("model") or "unknown"
    tags_model_label = _infer_tags_model(tags)
    review_model = rv.get("model") or "unknown"

    lines = [
        f"# Pipeline Review — {track_id}",
        "",
        f"*Source record: `{out_dir / track_id}.json`*",
        "",
        "---",
        "",
        "## Pipeline Settings",
        "",
        "| Stage | Model |",
        "|-------|-------|",
        f"| Audio Impression | {model_label(imp_model)} |",
        f"| CLAP Tagger | {tags_model_label} |",
        f"| AI Reviewer | {_infer_model(review_model)} |",
        "",
        "---",
        "",
        "## Source & Hard Facts",
        "",
        f"- **Master:** `{source.get('path', 'unknown')}`",
        f"- **Proxy:** `{source.get('proxy', 'n/a')}`",
        (f"- **Duration:** {_fmt_duration(hf.get('duration_s', 0))}"
         f"  |  **BPM:** {hf.get('bpm', '?')}"
         f"  |  **Key:** {hf.get('key', '?')} {hf.get('mode', '').strip()}"
         f"  |  **Time sig:** {hf.get('time_signature', '?')}"),
        f"- **LUFS:** {hf.get('lufs', '?')} dB"
        f"  |  **BPM confidence:** {conf.get('bpm', 0):.2f}"
        f"  |  **Key confidence:** {conf.get('key', 0):.2f}",
        f"- **Structure ({len(sections)} sections):** {section_str}",
        "",
        "---",
        "",
        "## Audio Impression",
        f"*{model_label(imp_model)}*",
        "",
        imp.get("text") or "*(not run)*",
        "",
        "---",
        "",
        "## CLAP Tags",
        f"*{tags_model_label}*",
        "",
        f"| Category | Tags |",
        f"|----------|------|",
        f"| Genre | {', '.join(tags.get('genre', [])) or 'n/a'} |",
        f"| Mood | {', '.join(tags.get('mood', [])) or 'n/a'} |",
        f"| Instruments | {', '.join(tags.get('instruments', [])) or 'n/a'} |",
        "",
        "---",
        "",
        "## Lyrics",
        "",
        "```",
        _truncate(record.get("lyrics") or "*(none)*"),
        "```",
        "",
        "---",
        "",
        "## Artist Persona",
        "",
        _truncate(record.get("persona") or "*(none)*", lines=6),
        "",
        "---",
        "",
        "## Standalone Review",
        f"*{model_label(review_model)}*",
        "",
        f"**Rank {vt.get('rank', '?')} — {vt.get('label', '?')}**"
        f"  |  Target: {rv.get('target', '?')}"
        f"  |  Status: {rv.get('status', '?')}",
        "",
        rv.get("review_text", "*(none)*"),
        "",
        f"**Anchors:** {', '.join(rv.get('anchors_used', [])) or 'none'}",
    ]

    return "\n".join(lines)


# ── Album pipeline doc ────────────────────────────────────────────────────────

def _album_doc(record: dict, out_dir: Path) -> str:
    album_id = record.get("album_id", "unknown")
    release_slug = record.get("release_slug", "")
    artist = record.get("artist", "")
    af = record.get("album_features", {})
    co = record.get("cohesion", {})
    rv = record.get("review", {})
    vt = rv.get("verdict_tier", {})
    tic_list = record.get("track_reviews_in_context", [])
    tracklist = record.get("tracklist", [])

    # Gather per-track sub-records
    track_records: dict[str, dict] = {}
    for tid in tracklist:
        td = _load_json(out_dir / f"{tid}.json")
        if td:
            track_records[tid] = td

    # Model provenance — gather from sub-records and album record
    imp_models = list({
        td.get("impression", {}).get("model", "") or "unknown"
        for td in track_records.values()
    })
    tags_label = " / ".join({
        _infer_tags_model(td.get("tags", {}))
        for td in track_records.values()
    }) or "unknown (predates tracking)"
    reviewer_models = list({
        td.get("review", {}).get("model", "") or "unknown"
        for td in track_records.values()
    })
    album_model = rv.get("model") or "unknown"
    ctx_models = list({t.get("model", "") or "unknown" for t in tic_list})

    def _model_cell(models: list[str]) -> str:
        labels = [_infer_model(m) for m in models if m]
        return " / ".join(labels) if labels else "unknown (predates tracking)"

    lines = [
        f"# Pipeline Review — {artist}: {release_slug}",
        "",
        f"*Album ID: `{album_id}`  |  Source record: `{out_dir / album_id}.json`*",
        "",
        "---",
        "",
        "## Pipeline Settings",
        "",
        "| Stage | Model |",
        "|-------|-------|",
        f"| Audio Impression (per track) | {_model_cell(imp_models)} |",
        f"| CLAP Tagger (per track) | {tags_label} |",
        f"| Track Reviewer (per track) | {_model_cell(reviewer_models)} |",
        f"| Album Synthesis | {_infer_model(album_model)} |",
        f"| Recontextualize (per track) | {_model_cell(ctx_models)} |",
        "",
        "---",
        "",
        "## Album Features",
        "",
        f"- **Runtime:** {int(af.get('total_runtime_s', 0) // 60)}m "
        f"{int(af.get('total_runtime_s', 0) % 60)}s",
        f"- **Rank distribution:** {af.get('rank_distribution', {})}",
        f"- **Strongest track:** {af.get('peak_track', '').split('--', 1)[-1]}",
        "",
        "| # | Track | BPM | Key | Mood | Rank |",
        "|---|-------|-----|-----|------|------|",
    ]

    bpm_curve = af.get("bpm_curve", [])
    key_prog = af.get("key_progression", [])
    mood_prog = af.get("mood_progression", [])

    for i, tid in enumerate(tracklist):
        short = tid.split("--", 1)[-1]
        td = track_records.get(tid, {})
        rank = td.get("review", {}).get("verdict_tier", {}).get("rank", "?")
        bpm = bpm_curve[i] if i < len(bpm_curve) else "?"
        key = key_prog[i] if i < len(key_prog) else "?"
        mood = mood_prog[i] if i < len(mood_prog) else "?"
        lines.append(f"| {i+1} | `{short}` | {bpm} | {key} | {mood} | {rank} |")

    lines += [
        "",
        "---",
        "",
        "## Cohesion",
        f"*Method: discrete_tags, 39-dim centroid cosine*",
        "",
        f"- **Palette consistency:** {co.get('palette_consistency', 0):.2f}"
        f"  ({co.get('verdict') or 'uncalibrated'})",
        f"- **Theme threads:** {', '.join(co.get('theme_threads', [])) or 'none'}",
        "",
        "---",
        "",
        "## Album Review",
        f"*{model_label(album_model)}*",
        "",
        f"**Rank {vt.get('rank', '?')} — {vt.get('label', '?')}**"
        f"  |  Sum vs parts: {rv.get('sum_vs_parts', '?')}"
        f"  |  Persona: {rv.get('persona_delivery', '?')}"
        f"  |  Status: {rv.get('status', '?')}",
        "",
        rv.get("review_text", "*(none)*"),
        "",
        f"**Anchors:** {', '.join(rv.get('anchors_used', [])) or 'none'}",
        "",
        "---",
        "",
        "## Track Details",
        "",
    ]

    for tic in tic_list:
        tid = tic.get("track_id", "")
        short = tid.split("--", 1)[-1]
        pos = tic.get("position", "?")
        s_rank = tic.get("standalone_rank", "?")
        c_rank = tic.get("context_rank")
        ctx_model = tic.get("model") or "unknown"

        if c_rank is not None:
            direction = "↑" if c_rank > s_rank else "↓"
            rank_line = f"standalone {s_rank} → context {c_rank} {direction}"
        else:
            rank_line = f"standalone {s_rank} | context: no change"

        td = track_records.get(tid, {})
        imp_text = td.get("impression", {}).get("impression_text") or \
                   td.get("impression", {}).get("text") or "*(not available)*"
        imp_model_t = td.get("impression", {}).get("model") or "unknown"
        tags = td.get("tags", {})
        standalone_text = td.get("review", {}).get("review_text", "*(not available)*")
        contextual_text = tic.get("review_text", "*(not available)*")

        lines += [
            f"### [{pos}] {short}  —  {rank_line}",
            "",
            f"**Audio Impression** *({model_label(imp_model_t)})*",
            "",
            imp_text,
            "",
            f"**CLAP Tags** *({_infer_tags_model(tags)})*  "
            f"Genre: {', '.join(tags.get('genre', [])) or 'n/a'}  |  "
            f"Mood: {', '.join(tags.get('mood', [])) or 'n/a'}  |  "
            f"Instruments: {', '.join(tags.get('instruments', [])) or 'n/a'}",
            "",
            "**Standalone Review**",
            "",
            standalone_text,
        ]

        if contextual_text != standalone_text:
            lines += [
                "",
                f"**Contextual Review** *({model_label(ctx_model)})*",
            ]
            if c_rank is not None:
                lines.append(f"*Context note: {tic.get('context_note', '')}*")
            lines += ["", contextual_text]

        lines.append("")

    return "\n".join(lines)


# ── Entry point ───────────────────────────────────────────────────────────────

def show(id_: str, save: bool = False, out_dir: Path | None = None) -> str:
    out_dir = out_dir or OUT_DIR
    record, mode = _resolve(id_, out_dir)

    doc = _track_doc(record, out_dir) if mode == "track" else _album_doc(record, out_dir)

    if save:
        safe_id = id_.replace("/", "-")
        save_path = out_dir / f"pipeline_{safe_id}.md"
        save_path.write_text(doc)
        print(f"Pipeline doc → {save_path}")

    return doc


def _main() -> None:
    parser = argparse.ArgumentParser(description="MRP Critic — pipeline review document")
    parser.add_argument("id", help="track_id (e.g. pcbender--apa) or release_slug (e.g. tria)")
    parser.add_argument("--save", action="store_true", help="Save to out/pipeline_<id>.md")
    parser.add_argument("--out", help="Output directory for records")
    args = parser.parse_args()

    out_dir = Path(args.out) if args.out else OUT_DIR
    doc = show(args.id, save=args.save, out_dir=out_dir)
    print(doc)


if __name__ == "__main__":
    _main()
