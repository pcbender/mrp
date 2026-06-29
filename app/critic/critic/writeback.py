"""Write critic review output as Astro content collection files."""
from __future__ import annotations

import json
from pathlib import Path

from .config import OUT_DIR
from .utils import scrub_emdash

REPO_ROOT = Path(__file__).resolve().parents[3]
REVIEWS_DIR = REPO_ROOT / "site" / "src" / "content" / "reviews"


def _yaml_str(value: str) -> str:
    escaped = value.replace("\\", "\\\\").replace('"', '\\"').replace("\n", " ")
    return f'"{escaped}"'


def write_review(record_id: str, out_dir: Path | None = None, force: bool = False) -> dict:
    source_dir = out_dir or OUT_DIR
    record_path = source_dir / f"{record_id}.json"
    if not record_path.is_file():
        return {"record_id": record_id, "status": "missing",
                "message": f"no critic record at {record_path}"}

    record = json.loads(record_path.read_text(encoding="utf-8"))

    # Distinguish track records from album records
    is_album = "album_id" in record
    slug = record.get("album_id") or record.get("track_id") or record_id

    impression = scrub_emdash(record.get("impression", {}).get("text", "")) if not is_album else ""
    review_text = scrub_emdash(record.get("review", {}).get("review_text", ""))
    verdict = record.get("review", {}).get("verdict_tier", {})
    verdict_rank = verdict.get("rank")
    verdict_label = verdict.get("label", "")

    if not review_text:
        return {"record_id": record_id, "status": "skipped",
                "message": "no review_text in critic record"}

    out_path = REVIEWS_DIR / f"{slug}.md"
    if out_path.is_file() and not force:
        return {"record_id": record_id, "status": "cached",
                "path": str(out_path.relative_to(REPO_ROOT))}

    lines = ["---", f"track_id: {slug}"]
    if impression:
        lines.append(f"impression: {_yaml_str(impression)}")
    if verdict_rank is not None:
        lines.append(f"verdict_rank: {verdict_rank}")
    if verdict_label:
        lines.append(f"verdict_label: {_yaml_str(verdict_label)}")
    lines += ["---", ""]
    lines.append(review_text)
    lines.append("")

    REVIEWS_DIR.mkdir(parents=True, exist_ok=True)
    out_path.write_text("\n".join(lines), encoding="utf-8")
    return {"record_id": record_id, "status": "ok",
            "path": str(out_path.relative_to(REPO_ROOT))}


def write_all(out_dir: Path | None = None, force: bool = False) -> list[dict]:
    source_dir = out_dir or OUT_DIR
    results = []
    for record_path in sorted(source_dir.glob("*.json")):
        result = write_review(record_path.stem, out_dir=source_dir, force=force)
        results.append(result)
        print(f"  {record_path.stem:45s}  [{result['status']}]")
    return results


def cmd_writeback(args) -> None:
    out_dir = Path(args.out) if args.out else OUT_DIR
    if args.track:
        result = write_review(args.track, out_dir=out_dir, force=args.force)
        print(f"  {args.track:45s}  [{result['status']}]")
        if result["status"] == "missing":
            print(f"  {result['message']}")
            raise SystemExit(1)
    else:
        write_all(out_dir=out_dir, force=args.force)
