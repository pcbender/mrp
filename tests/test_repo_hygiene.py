import os
import subprocess
from pathlib import Path

import pytest

from mrp.core.output import site_out_root


ROOT = Path(__file__).resolve().parents[1]
FORBIDDEN_TRACKED_PREFIXES = (
    "builds/",
    "graphify-out/",
    "site/dist/",
    "site/.astro/",
    "node_modules/",
    "site/node_modules/",
)
# graphify publishes these three as committed artifacts, and .gitignore
# un-ignores exactly them under an otherwise-ignored graphify-out/. The rest of
# that directory — cache/, manifest.json, the dated snapshots — stays generated,
# so the prefix ban above still applies to it. Keep this in step with the
# "!graphify-out/..." lines in .gitignore.
ALLOWED_TRACKED_PATHS = frozenset(
    {
        "graphify-out/GRAPH_REPORT.md",
        "graphify-out/graph.html",
        "graphify-out/graph.json",
    }
)
FORBIDDEN_GENERATED_DIRS = (
    "builds",
    "site/dist",
    "site/.astro",
)


def test_generated_and_dependency_paths_are_not_tracked():
    result = subprocess.run(
        ["git", "ls-files"],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    tracked = result.stdout.splitlines()
    offenders = [
        path
        for path in tracked
        if path not in ALLOWED_TRACKED_PATHS
        and (
            path == "node_modules"
            or path == "site/node_modules"
            or path.startswith(FORBIDDEN_TRACKED_PREFIXES)
        )
    ]
    assert offenders == []


def test_generated_website_output_dirs_do_not_exist_under_repo():
    offenders = [path for path in FORBIDDEN_GENERATED_DIRS if (ROOT / path).exists()]

    assert offenders == []


def test_site_output_root_rejects_repo_internal_directory(monkeypatch):
    monkeypatch.setenv("MRP_SITE_OUT_ROOT", str(ROOT / "builds"))

    with pytest.raises(ValueError, match="inside repository"):
        site_out_root(ROOT)
