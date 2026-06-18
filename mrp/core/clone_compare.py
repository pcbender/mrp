from __future__ import annotations

import json
import re
from collections import Counter
from datetime import UTC, datetime
from html import unescape
from html.parser import HTMLParser
from pathlib import Path
from typing import Any

from mrp.core.deploy import load_targets, validate_target
from mrp.core.migration_inventory import DEFAULT_MIGRATION_SOURCE, resolve_source
from mrp.core.verify import normalize_target, route_to_html_relative


PAGE_ROOT_RELATIVE = Path("live-capture/raw/pages/www.maricoparecords.com")
REPRESENTATIVE_ROUTES = [
    {
        "route": "/",
        "markers": ["Maricopa Records"],
    },
    {
        "route": "/artists/pcbender/",
        "markers": ["mystique"],
    },
    {
        "route": "/artists/pcbender/circuiting/",
        "markers": ["Circuiting is not just an album"],
    },
    {
        "route": "/licensing-custom-songs/music-licensing/",
        "markers": ["Music Licensing"],
    },
    {
        "route": "/2025/02/26/the-future-of-ai-in-music/",
        "markers": ["The Future of AI in Music"],
    },
]
CONTAINER_PREFIXES = ("wp-", "wp-block", "stk-", "ugb-", "cryout", "tmm")


def clone_compare(
    repo: str | Path,
    source: str | Path = DEFAULT_MIGRATION_SOURCE,
    target: str | None = None,
) -> dict[str, Any]:
    root = Path(repo).resolve()
    generated_at = now_utc()
    result = {
        "command": "clone-compare",
        "repo": str(root),
        "source": str(Path(source).expanduser()),
        "requested_target": target,
        "target": normalize_target(target),
        "generated_at": generated_at,
        "comparisons": [],
        "failures": [],
        "warnings": [],
    }
    try:
        source_paths = resolve_source(source)
        target_path = resolve_target(root, result["target"])
        result["source_files"] = {"page_root": str(source_paths["artifact_root"] / PAGE_ROOT_RELATIVE)}
        result["target_path"] = str(target_path.relative_to(root))
        result.update(run_comparison(source_paths["artifact_root"] / PAGE_ROOT_RELATIVE, target_path))
    except (FileNotFoundError, ValueError) as exc:
        result["failures"].append({"route": None, "field": "config", "message": str(exc)})
    result["status"] = "failed" if result["failures"] else "completed"
    result["summary"] = {
        "routes_compared": len(result["comparisons"]),
        "passed": sum(1 for item in result["comparisons"] if item["status"] == "passed"),
        "warnings": len(result["warnings"]),
        "failures": len(result["failures"]),
    }
    result["report_path"] = write_report(root, generated_at, result)
    return result


def resolve_target(root: Path, target_name: str) -> Path:
    targets, config_errors = load_targets(root)
    if config_errors:
        raise ValueError("; ".join(config_errors))
    if target_name not in targets:
        raise ValueError(f"Unknown compare target: {target_name}")
    safety = validate_target(root, target_name, targets[target_name])
    if safety["status"] != "passed":
        raise ValueError(safety["message"])
    return root / safety["target_path"]


def run_comparison(page_root: Path, target_path: Path) -> dict[str, Any]:
    if not page_root.is_dir():
        raise FileNotFoundError(f"Missing captured page root: {page_root}")
    if not target_path.is_dir():
        raise FileNotFoundError(f"Missing target path: {target_path}")

    comparisons = []
    failures = []
    warnings = []
    for fixture in REPRESENTATIVE_ROUTES:
        route = fixture["route"]
        source_file = page_root / route_to_html_relative(route)
        target_file = target_path / route_to_html_relative(route)
        comparison = compare_route(route, fixture["markers"], source_file, target_file, failures, warnings)
        comparisons.append(comparison)
    return {"comparisons": comparisons, "failures": failures, "warnings": warnings}


def compare_route(
    route: str,
    markers: list[str],
    source_file: Path,
    target_file: Path,
    failures: list[dict[str, Any]],
    warnings: list[dict[str, Any]],
) -> dict[str, Any]:
    comparison = {
        "route": route,
        "source_path": str(source_file),
        "target_path": str(target_file),
        "status": "passed",
        "checks": {},
    }
    if not source_file.is_file():
        add_issue(failures, route, "source", f"Missing captured source page: {source_file}")
    if not target_file.is_file():
        add_issue(failures, route, "target", f"Missing rendered target page: {target_file}")
    if failures and failures[-1].get("route") == route:
        comparison["status"] = "failed"
        return comparison

    source = HtmlSnapshot.from_text(source_file.read_text(errors="ignore"))
    target = HtmlSnapshot.from_text(target_file.read_text(errors="ignore"))
    comparison["checks"] = {
        "title": compare_title(route, source, target, warnings),
        "headings": compare_headings(route, source, target, warnings),
        "markers": compare_markers(route, markers, source, target, failures),
        "asset_references": compare_asset_references(route, source, target, warnings),
        "major_containers": compare_containers(route, source, target, warnings),
    }
    if any(issue["route"] == route for issue in failures):
        comparison["status"] = "failed"
    elif any(issue["route"] == route for issue in warnings):
        comparison["status"] = "warn"
    return comparison


def compare_title(route: str, source: "HtmlSnapshot", target: "HtmlSnapshot", warnings: list[dict[str, Any]]) -> dict[str, Any]:
    source_title = normalize_text(source.title)
    target_title = normalize_text(target.title)
    matched = bool(
        source_title
        and target_title
        and (
            source_title in target_title
            or target_title in source_title
            or comparable_title(source_title) == comparable_title(target_title)
        )
    )
    if not matched:
        add_issue(warnings, route, "title", f"Title differs: source={source_title!r}, target={target_title!r}")
    return {"source": source_title, "target": target_title, "matched": matched}


def comparable_title(value: str) -> str:
    return normalize_text(value.replace(" | ", " - "))


def compare_headings(route: str, source: "HtmlSnapshot", target: "HtmlSnapshot", warnings: list[dict[str, Any]]) -> dict[str, Any]:
    source_headings = [normalize_text(item) for item in source.headings if normalize_text(item)]
    target_headings = [normalize_text(item) for item in target.headings if normalize_text(item)]
    overlap = sorted(set(source_headings) & set(target_headings))
    if source_headings and not overlap:
        add_issue(warnings, route, "headings", "No matching headings found between captured and rendered pages.")
    return {"source_count": len(source_headings), "target_count": len(target_headings), "overlap": overlap[:10]}


def compare_markers(
    route: str,
    markers: list[str],
    source: "HtmlSnapshot",
    target: "HtmlSnapshot",
    failures: list[dict[str, Any]],
) -> dict[str, Any]:
    missing = []
    for marker in markers:
        if marker not in source.text:
            missing.append({"marker": marker, "side": "source"})
        if marker not in target.text:
            missing.append({"marker": marker, "side": "target"})
    for item in missing:
        add_issue(failures, route, "marker", f"Missing marker in {item['side']}: {item['marker']}")
    return {"checked": len(markers), "missing": missing}


def compare_asset_references(route: str, source: "HtmlSnapshot", target: "HtmlSnapshot", warnings: list[dict[str, Any]]) -> dict[str, Any]:
    source_count = len(source.wordpress_assets)
    target_count = len(target.static_wordpress_assets)
    if source_count and not target_count:
        add_issue(warnings, route, "asset_references", "Captured page has WordPress assets but rendered page has no /assets/wp references.")
    return {"source_wordpress_assets": source_count, "target_static_wordpress_assets": target_count}


def compare_containers(route: str, source: "HtmlSnapshot", target: "HtmlSnapshot", warnings: list[dict[str, Any]]) -> dict[str, Any]:
    source_containers = source.major_classes
    target_containers = target.major_classes
    overlap = sorted(source_containers & target_containers)
    if source_containers and not overlap:
        add_issue(warnings, route, "major_containers", "No major WordPress/Stackable container classes overlap.")
    return {"source_count": len(source_containers), "target_count": len(target_containers), "overlap": overlap[:20]}


def add_issue(issues: list[dict[str, Any]], route: str | None, field: str, message: str) -> None:
    issues.append({"route": route, "field": field, "message": message})


class HtmlSnapshot(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.title = ""
        self.headings: list[str] = []
        self.text_parts: list[str] = []
        self.wordpress_assets: set[str] = set()
        self.static_wordpress_assets: set[str] = set()
        self.major_classes: set[str] = set()
        self._current_tag: str | None = None
        self._buffer: list[str] = []

    @classmethod
    def from_text(cls, text: str) -> "HtmlSnapshot":
        parser = cls()
        parser.feed(text)
        parser.close()
        parser.text = normalize_text(" ".join(parser.text_parts))
        parser.wordpress_assets.update(re.findall(r"""(?:https?:)?//(?:www\.)?maricoparecords\.com/(?:wp-content|wp-includes)/[^\s"'<>]+""", text))
        parser.static_wordpress_assets.update(re.findall(r"""/assets/wp/[^\s"'<>),]+""", text))
        return parser

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attrs_dict = {name: value or "" for name, value in attrs}
        for name in ("href", "src", "poster"):
            value = attrs_dict.get(name, "")
            if "/wp-content/" in value or "/wp-includes/" in value:
                self.wordpress_assets.add(value)
            if value.startswith("/assets/wp/"):
                self.static_wordpress_assets.add(value)
        classes = attrs_dict.get("class", "").split()
        for class_name in classes:
            if class_name.startswith(CONTAINER_PREFIXES):
                self.major_classes.add(class_name)
        if tag in {"title", "h1", "h2", "h3"}:
            self._current_tag = tag
            self._buffer = []

    def handle_endtag(self, tag: str) -> None:
        if tag != self._current_tag:
            return
        text = normalize_text(" ".join(self._buffer))
        if tag == "title":
            self.title = text
        elif text:
            self.headings.append(text)
        self._current_tag = None
        self._buffer = []

    def handle_data(self, data: str) -> None:
        text = unescape(data)
        if self._current_tag:
            self._buffer.append(text)
        if text.strip():
            self.text_parts.append(text)


def normalize_text(value: str) -> str:
    return re.sub(r"\s+", " ", unescape(value or "")).strip()


def write_report(root: Path, generated_at: str, result: dict[str, Any]) -> str:
    timestamp = generated_at.replace("-", "").replace(":", "").replace("Z", "Z")
    path = root / "reports" / "comparison" / f"{timestamp}-clone-compare.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n")
    return str(path.relative_to(root))


def now_utc() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def format_clone_compare(report: dict[str, Any]) -> str:
    summary = report["summary"]
    return "\n".join(
        [
            f"Clone comparison {report['status']}",
            f"Routes compared: {summary['routes_compared']}",
            f"Passed: {summary['passed']}",
            f"Warnings: {summary['warnings']}",
            f"Failures: {summary['failures']}",
            f"Report: {report['report_path']}",
        ]
    )
