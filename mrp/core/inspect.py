from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml


CONTENT_EXTENSIONS = {".yaml", ".yml", ".json"}
REPORT_DIRS = [
    "validation",
    "build",
    "deployment",
    "verification",
    "approval",
    "rollback",
    "import",
]


@dataclass(frozen=True)
class ContentCounts:
    artists: int
    releases: int
    assets: int
    site: int

    @property
    def total(self) -> int:
        return self.artists + self.releases + self.assets + self.site


def inspect_repository(repo: str | Path) -> dict[str, Any]:
    root = Path(repo).resolve()
    counts = count_content(root)
    framework = detect_site_framework(root)
    deploy = inspect_deploy(root)
    reports = latest_reports(root)
    warnings = inspect_warnings(root, counts, framework, deploy)

    return {
        "command": "inspect",
        "status": "ok",
        "repo": str(root),
        "site_framework": framework,
        "content": {
            "records": counts.total,
            "artists": counts.artists,
            "releases": counts.releases,
            "assets": counts.assets,
            "site": counts.site,
        },
        "deploy": deploy,
        "reports": reports,
        "warnings": warnings,
    }


def count_content(root: Path) -> ContentCounts:
    content = root / "content"
    site = 1 if (content / "site.yaml").is_file() else 0
    artists = count_record_files(content / "artists")
    releases = count_record_files(content / "releases")
    assets = count_assets(content / "assets" / "manifest.yaml")
    return ContentCounts(artists=artists, releases=releases, assets=assets, site=site)


def count_record_files(path: Path) -> int:
    if not path.is_dir():
        return 0
    return sum(1 for item in path.iterdir() if item.is_file() and item.suffix in CONTENT_EXTENSIONS)


def count_assets(manifest: Path) -> int:
    if not manifest.is_file():
        return 0
    data = yaml.safe_load(manifest.read_text()) or {}
    assets = data.get("assets", [])
    return len(assets) if isinstance(assets, list) else 0


def detect_site_framework(root: Path) -> dict[str, Any]:
    site = root / "site"
    package_json = site / "package.json"
    astro_config = site / "astro.config.mjs"
    root_astro_config = root / "astro.config.mjs"

    if astro_config.is_file() or root_astro_config.is_file():
        return {
            "name": "astro",
            "detected": True,
            "path": str((astro_config if astro_config.is_file() else root_astro_config).relative_to(root)),
        }
    if package_json.is_file():
        return {"name": "unknown-node", "detected": True, "path": str(package_json.relative_to(root))}
    return {"name": None, "detected": False, "path": None}


def inspect_deploy(root: Path) -> dict[str, Any]:
    deploy = root / "deploy"
    return {
        "directory": deploy.is_dir(),
        "targets": (deploy / "targets.yaml").is_file(),
        "local_targets": (deploy / "targets.local.yaml").is_file(),
        "allow_deploy_example": (deploy / ".allow-deploy.example").is_file(),
    }


def latest_reports(root: Path) -> dict[str, str | None]:
    reports_root = root / "reports"
    latest: dict[str, str | None] = {}
    for name in REPORT_DIRS:
        report_dir = reports_root / name
        candidates = sorted(report_dir.glob("*.json")) if report_dir.is_dir() else []
        latest[name] = str(candidates[-1].relative_to(root)) if candidates else None
    return latest


def inspect_warnings(
    root: Path,
    counts: ContentCounts,
    framework: dict[str, Any],
    deploy: dict[str, Any],
) -> list[str]:
    warnings: list[str] = []
    if not framework["detected"]:
        warnings.append("No static site framework detected yet.")
    if counts.artists == 0:
        warnings.append("No artist records found.")
    if counts.releases == 0:
        warnings.append("No release records found.")
    if counts.assets == 0:
        warnings.append("No asset manifest records found.")
    if not deploy["targets"]:
        warnings.append("No deploy/targets.yaml file found.")
    if not (root / "content" / "site.yaml").is_file():
        warnings.append("Missing content/site.yaml.")
    return warnings


def format_inspection(result: dict[str, Any]) -> str:
    content = result["content"]
    framework = result["site_framework"]
    deploy = result["deploy"]
    lines = [
        "MRP repository inspection",
        f"Repository: {result['repo']}",
        f"Site framework: {framework['name'] or 'not detected'}",
        f"Content records: {content['records']}",
        f"Artists: {content['artists']}",
        f"Releases: {content['releases']}",
        f"Assets: {content['assets']}",
        f"Deploy config: {'present' if deploy['targets'] else 'missing'}",
    ]
    if result["warnings"]:
        lines.append("Warnings:")
        lines.extend(f"- {warning}" for warning in result["warnings"])
    return "\n".join(lines)
