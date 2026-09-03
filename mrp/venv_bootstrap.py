"""Re-exec an entry script under the repository's own interpreter.

`scripts/mrp` and `scripts/mrp-admin` start with `#!/usr/bin/env python3`,
which resolves through PATH: run either without activating the venv first and
they get the system interpreter, which has none of the project's dependencies.
That surfaces as a bare `ModuleNotFoundError` — `No module named 'PIL'` from
`mrp admin serve` — rather than anything pointing at the real cause.

So find `<repo>/.venv` the way `mrp.admin.video_jobs.worker_python` already
finds it for renderer child processes, and hand the process over to it. This
module is imported before the venv is in play, so it must stay stdlib-only and
must not import anything else from `mrp`.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

# Set across the exec so a venv that cannot run the script fails with its own
# error instead of trading execs with us forever.
_SENTINEL = "MRP_VENV_REEXEC"

# Escape hatch for deliberately running under some other interpreter.
_OPT_OUT = "MRP_NO_VENV_REEXEC"


def repo_interpreter(root: Path) -> Path | None:
    """The repo venv's python, or None when there is no venv to use."""
    candidates = (
        root / ".venv" / "bin" / "python",
        root / ".venv" / "Scripts" / "python.exe",
    )
    return next((path for path in candidates if path.is_file()), None)


def running_inside(root: Path) -> bool:
    """True when the current interpreter belongs to the repo venv.

    Compares sys.prefix against the venv directory rather than comparing
    executables: `.venv/bin/python` is usually a symlink to the same system
    binary, so resolving both paths reports a false match when running
    unactivated. sys.prefix is the venv root only when the venv is in use.
    """
    try:
        return Path(sys.prefix).resolve() == (root / ".venv").resolve()
    except OSError:
        return False


def ensure_repo_interpreter(root: str | os.PathLike[str]) -> None:
    """Hand off to the repo venv's python, if we are not already using it.

    Does nothing — deliberately, rather than failing — when there is no venv
    yet, so a fresh checkout still reaches the script's own error handling.
    """
    if os.environ.get(_OPT_OUT) or os.environ.get(_SENTINEL):
        return
    root_path = Path(root).resolve()
    if running_inside(root_path):
        return
    python = repo_interpreter(root_path)
    if python is None:
        return
    os.environ[_SENTINEL] = "1"
    os.execv(str(python), [str(python), *sys.argv])
