from __future__ import annotations

import json
import re
import unicodedata
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from mrp.core.lyrics_text import clean_lyrics, extract_primary_section
from mrp.core.migrate_site import load_structured_record, serialize_structured_record

NON_LYRIC_DOC_PATTERN = re.compile(r"(?i)\bsuno\b|\bprompt\b|\btemplate\b|\breference\b|\bguide\b|\blexicon\b")
QUOTE_TRANSLATION = {ord("’"): "'", ord("‘"): "'", ord("“"): '"', ord("”"): '"'}


def _title_key(title: str) -> str:
    value = (title or "").translate(QUOTE_TRANSLATION)
    normalized = unicodedata.normalize("NFKD", value).encode("ascii", "ignore").decode("ascii")
    return re.sub(r"[^a-z0-9]+", "-", normalized.lower()).strip("-")


def _load_units(releases_dir: Path, root: Path) -> dict[str, list[dict[str, Any]]]:
    units_by_key: dict[str, list[dict[str, Any]]] = {}
    if not releases_dir.is_dir():
        return units_by_key

    for path in sorted(p for p in releases_dir.glob("*") if p.suffix in {".yaml", ".yml", ".json"}):
        data = load_structured_record(path)
        release = data.get("release")
        if not isinstance(release, dict):
            continue

        song = release.get("song")
        if isinstance(song, dict):
            key = _title_key(song.get("title") or "")
            units_by_key.setdefault(key, []).append(
                {"path": path, "data": data, "container": song, "kind": "song", "slug": None, "title": song.get("title")}
            )

        for track in release.get("tracks") or []:
            if isinstance(track, dict):
                key = _title_key(track.get("title") or "")
                units_by_key.setdefault(key, []).append(
                    {
                        "path": path,
                        "data": data,
                        "container": track,
                        "kind": "track",
                        "slug": track.get("slug"),
                        "title": track.get("title"),
                    }
                )

    return units_by_key


def enrich_lyrics(
    repo: str | Path,
    docs: list[dict[str, Any]],
    dry_run: bool = False,
) -> dict[str, Any]:
    root = Path(repo).resolve()
    units_by_key = _load_units(root / "content" / "releases", root)

    path_to_data = {unit["path"]: unit["data"] for units in units_by_key.values() for unit in units}

    patched: list[dict[str, Any]] = []
    multi_target: list[dict[str, Any]] = []
    unmatched_docs: list[dict[str, str]] = []
    skipped_already_set = 0
    skipped_non_lyric = 0
    dirty_paths: set[Path] = set()
    matched_keys: set[str] = set()

    for doc in docs:
        doc_id = doc.get("id")
        title = doc.get("title") or ""
        content = doc.get("content") or ""

        if NON_LYRIC_DOC_PATTERN.search(title):
            skipped_non_lyric += 1
            continue

        key = _title_key(title)
        targets = units_by_key.get(key, [])
        if not targets:
            unmatched_docs.append({"id": doc_id, "title": title})
            continue

        matched_keys.add(key)
        lyrics_text = clean_lyrics(extract_primary_section(content))
        lyrics_source = f"https://docs.google.com/document/d/{doc_id}/edit"

        added_for_doc: list[str] = []
        for target in targets:
            container = target["container"]
            if container.get("lyrics_text"):
                skipped_already_set += 1
                continue
            container["lyrics_text"] = lyrics_text
            container["lyrics_source"] = lyrics_source
            dirty_paths.add(target["path"])
            label = f"{target['path'].name}:{target['slug'] or target['kind']}"
            added_for_doc.append(label)

        if added_for_doc:
            entry = {"doc_id": doc_id, "title": title, "applied_to": added_for_doc}
            if len(targets) > 1:
                multi_target.append(entry)
            else:
                patched.append(entry)

    unmatched_units = [
        {"path": str(unit["path"].relative_to(root)), "kind": unit["kind"], "slug": unit["slug"], "title": unit["title"]}
        for key, units in units_by_key.items()
        if key not in matched_keys
        for unit in units
        if not unit["container"].get("lyrics_text")
    ]

    if not dry_run:
        for path in dirty_paths:
            path.write_text(serialize_structured_record(path, path_to_data[path]))

    generated_at = now_iso()
    report = {
        "command": "enrich-lyrics",
        "status": "passed",
        "repo": str(root),
        "dry_run": dry_run,
        "generated_at": generated_at,
        "summary": {
            "docs_provided": len(docs),
            "skipped_non_lyric_doc": skipped_non_lyric,
            "songs_or_tracks_patched": sum(len(p["applied_to"]) for p in patched + multi_target),
            "docs_applied_to_one_target": len(patched),
            "docs_applied_to_multiple_targets": len(multi_target),
            "skipped_already_set": skipped_already_set,
            "unmatched_docs": len(unmatched_docs),
            "unmatched_songs_or_tracks": len(unmatched_units),
        },
        "patched": patched,
        "multi_target": multi_target,
        "unmatched_docs": unmatched_docs,
        "unmatched_songs_or_tracks": unmatched_units,
    }
    if not dry_run:
        report_path = root / "reports" / "enrichment" / f"{generated_at.replace('-', '').replace(':', '')}-lyrics.json"
        report_path.parent.mkdir(parents=True, exist_ok=True)
        report_path.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")
        report["report_path"] = str(report_path.relative_to(root))
    return report


def now_iso() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def format_enrich_lyrics(report: dict[str, Any]) -> str:
    summary = report["summary"]
    lines = [
        "Enrich-lyrics completed" + (" (dry run)" if report["dry_run"] else ""),
        f"Docs provided: {summary['docs_provided']} (skipped non-lyric: {summary['skipped_non_lyric_doc']})",
        f"Songs/tracks patched: {summary['songs_or_tracks_patched']}",
        f"Docs applied to one target: {summary['docs_applied_to_one_target']}",
        f"Docs applied to multiple targets (shared lyrics): {summary['docs_applied_to_multiple_targets']}",
        f"Skipped (already had lyrics_text): {summary['skipped_already_set']}",
        f"Unmatched docs: {summary['unmatched_docs']}",
        f"Unmatched songs/tracks: {summary['unmatched_songs_or_tracks']}",
    ]
    if report.get("report_path"):
        lines.append(f"Report: {report['report_path']}")
    return "\n".join(lines)
