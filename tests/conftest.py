import os
import shutil
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent


_SKIP_DIRS = {
    str(ROOT): {".git"},
    str(ROOT / "site"): {"node_modules", "dist", ".astro"},
}


def _ignore(directory: str, names: list[str]) -> set[str]:
    skip = _SKIP_DIRS.get(directory, set())
    return {name for name in names if name in skip or name == "__pycache__" or name.endswith(".pyc")}


@pytest.fixture
def isolated_repo(tmp_path: Path) -> Path:
    """A filesystem copy of the real repo for e2e tests that exercise the full
    CLI pipeline (migrate-site, clone-site, build, publish, rollback, ...).

    Those commands take an explicit --repo argument; passing this path instead
    of the real project root keeps them from ever mutating the live dev repo.
    node_modules is symlinked back in rather than copied (large, read-only).

    The skip list is scoped by directory (not bare basenames) because
    shutil.ignore_patterns matches names anywhere in the tree -- a bare
    "dist" pattern would also exclude legitimate asset dirs like
    site/public/assets/wp/wp-content/plugins/*/dist/.
    """
    repo = tmp_path / "repo"
    shutil.copytree(ROOT, repo, symlinks=True, ignore=_ignore)
    node_modules = ROOT / "site" / "node_modules"
    if node_modules.is_dir():
        os.symlink(node_modules, repo / "site" / "node_modules", target_is_directory=True)
    return repo
