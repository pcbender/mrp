from __future__ import annotations

import os
from pathlib import Path


DEFAULT_SITE_OUT_ROOT = Path.home() / "astro-sites" / "maricoparecords"


def site_out_root(repo_root: str | Path) -> Path:
    root = Path(repo_root).resolve()
    raw = os.environ.get("MRP_SITE_OUT_ROOT")
    output_root = Path(raw).expanduser() if raw else DEFAULT_SITE_OUT_ROOT
    output_root = output_root.resolve()
    assert_outside_repo(root, output_root)
    return output_root


def build_artifact_dir(repo_root: str | Path, build_id: str) -> Path:
    return site_out_root(repo_root) / "builds" / "staging" / build_id


def archive_root(repo_root: str | Path) -> Path:
    return site_out_root(repo_root) / "archive"


def resolve_output_path(repo_root: str | Path, path: str | Path) -> Path:
    root = Path(repo_root).resolve()
    candidate = Path(path).expanduser()
    if candidate.is_absolute():
        resolved = candidate.resolve()
    else:
        resolved = (site_out_root(root) / candidate).resolve()
    assert_outside_repo(root, resolved)
    assert_under_site_out_root(site_out_root(root), resolved)
    return resolved


def display_path(repo_root: str | Path, path: str | Path) -> str:
    root = Path(repo_root).resolve()
    target = Path(path).resolve()
    try:
        return str(target.relative_to(root))
    except ValueError:
        return str(target)


def path_from_report(repo_root: str | Path, path: str | Path) -> Path:
    candidate = Path(path).expanduser()
    if candidate.is_absolute():
        return candidate.resolve()
    return (Path(repo_root).resolve() / candidate).resolve()


def assert_outside_repo(repo_root: str | Path, target_dir: str | Path) -> None:
    root = Path(repo_root).resolve()
    target = Path(target_dir).resolve()
    if target == root or root in target.parents:
        raise ValueError(f"Refusing to write generated output inside repository: {target}")


def assert_under_site_out_root(site_root: str | Path, target_dir: str | Path) -> None:
    root = Path(site_root).resolve()
    target = Path(target_dir).resolve()
    if target != root and root not in target.parents:
        raise ValueError(f"Refusing to write outside configured site output root: {target}")
