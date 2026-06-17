from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from mrp.core.migration_inventory import DEFAULT_MIGRATION_SOURCE, migration_inventory


def migrate_site(
    repo: str | Path,
    source: str | Path = DEFAULT_MIGRATION_SOURCE,
    dry_run: bool = False,
) -> dict[str, Any]:
    root = Path(repo).resolve()
    generated_at = now_utc()
    result = {
        "command": "migrate-site",
        "repo": str(root),
        "source": str(Path(source).expanduser()),
        "generated_at": generated_at,
        "dry_run": dry_run,
    }

    if not dry_run:
        result.update(
            {
                "status": "failed",
                "stage": "config",
                "message": "migrate-site mutation mode is reserved for MRP-104.",
            }
        )
        result["report_path"] = write_migration_report(root, generated_at, result)
        return result

    try:
        inventory = migration_inventory(root, source, write_report=False)
    except FileNotFoundError as exc:
        result.update(
            {
                "status": "failed",
                "stage": "config",
                "message": str(exc),
            }
        )
        result["report_path"] = write_migration_report(root, generated_at, result)
        return result

    result.update(
        {
            "status": "planned",
            "stage": "dry_run",
            "summary": inventory["summary"],
            "source_files": inventory["source_files"],
            "planned_writes": planned_writes(inventory),
            "exclusions": {
                "commerce": len(inventory["exclusions"]["commerce"]),
                "feedback": len(inventory["exclusions"]["feedback"]),
            },
            "notes": [
                "Dry-run only; no content records or assets were written.",
                "Mutation mode is reserved for later v0.1.1 packets.",
            ],
        }
    )
    result["report_path"] = write_migration_report(root, generated_at, result)
    return result


def planned_writes(inventory: dict[str, Any]) -> dict[str, Any]:
    categories = inventory["summary"]["categories"]
    asset_categories = inventory["summary"]["asset_categories"]
    return {
        "pages": categories.get("public_page", 0),
        "posts": categories.get("blog_news_post", 0),
        "artist_records": inventory["summary"]["artist_routes"],
        "release_records": inventory["summary"]["release_routes"],
        "assets": asset_categories.get("candidate_media", 0),
        "normalized_urls": inventory["summary"]["normalized_routes"],
    }


def write_migration_report(root: Path, generated_at: str, result: dict[str, Any]) -> str:
    timestamp = generated_at.replace("-", "").replace(":", "").replace("Z", "Z")
    suffix = "dry-run" if result.get("dry_run") else "mutation-blocked"
    report_path = root / "reports" / "migration" / f"{timestamp}-{suffix}.json"
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n")
    return str(report_path.relative_to(root))


def now_utc() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def format_migrate_site(result: dict[str, Any]) -> str:
    lines = [
        f"Migrate-site {result['status']}",
        f"Report: {result['report_path']}",
    ]
    if result.get("planned_writes"):
        planned = result["planned_writes"]
        lines.extend(
            [
                f"Pages: {planned['pages']}",
                f"Posts: {planned['posts']}",
                f"Assets: {planned['assets']}",
            ]
        )
    if result.get("message"):
        lines.append(result["message"])
    return "\n".join(lines)
