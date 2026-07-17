"""Git operations for the admin Changes page.

Scoped strictly to the data pathspecs (content/, assets/, and public assets)
so admin commits can never sweep in code changes, and the user's staged work
elsewhere in the tree is left untouched (pathspec-limited `git commit --
<paths>` uses a temporary index).
"""
from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Any

DATA_PATHSPECS = ("content", "assets", "site/public/assets")
COMMIT_BRANCH = "main"
MAX_DIFF_LINES = 400

_STATUS_LABELS = {
    "M": "modified",
    "A": "added",
    "D": "deleted",
    "R": "renamed",
    "C": "copied",
    "T": "type-changed",
    "U": "conflict",
    "?": "new",
}


class GitError(RuntimeError):
    pass


def _git(root: Path, *args: str, check: bool = True) -> subprocess.CompletedProcess[str]:
    proc = subprocess.run(
        ["git", "-C", str(root), *args],
        capture_output=True,
        text=True,
    )
    if check and proc.returncode != 0:
        detail = (proc.stderr or proc.stdout).strip()
        raise GitError(detail or f"git {' '.join(args)} failed ({proc.returncode})")
    return proc


def current_branch(root: Path) -> str:
    return _git(root, "branch", "--show-current").stdout.strip()


def is_data_path(path: str) -> bool:
    parts = Path(path).parts
    if not parts or Path(path).is_absolute() or ".." in parts:
        return False
    # Prefix match per pathspec — specs may span segments (site/public/assets).
    return any(path == spec or path.startswith(spec + "/") for spec in DATA_PATHSPECS)


def data_changes(root: Path) -> list[dict[str, Any]]:
    """Working-tree changes (staged or not) under the data pathspecs."""
    out = _git(root, "status", "--porcelain=v1", "-z", "--", *DATA_PATHSPECS).stdout
    entries = []
    fields = out.split("\0")
    i = 0
    while i < len(fields):
        field = fields[i]
        if not field:
            i += 1
            continue
        code, path = field[:2], field[3:]
        if code[0] in ("R", "C"):
            # porcelain -z renames: "R  new-path" NUL "old-path"
            i += 1
        key = code[0] if code[0] != " " else code[1]
        untracked = code == "??"
        entries.append({
            "path": path,
            "code": code.strip(),
            "label": _STATUS_LABELS.get(key, code.strip()),
            "untracked": untracked,
        })
        i += 1
    entries.sort(key=lambda e: e["path"])
    return entries


def file_diff(root: Path, path: str, untracked: bool) -> dict[str, Any]:
    """Unified diff of a file's working-tree state against HEAD."""
    if untracked:
        proc = _git(root, "diff", "--no-index", "--", "/dev/null", path, check=False)
        if proc.returncode not in (0, 1):
            raise GitError((proc.stderr or proc.stdout).strip())
        raw = proc.stdout
    else:
        raw = _git(root, "diff", "HEAD", "--", path).stdout

    if any(line.startswith("Binary files") for line in raw.splitlines()[:8]):
        size = (root / path).stat().st_size if (root / path).exists() else 0
        return {"binary": True, "size": size, "lines": [], "truncated": False}

    lines = []
    for line in raw.splitlines():
        if line.startswith(("+++", "---", "diff --git", "index ", "new file", "deleted file")):
            cls = "meta"
        elif line.startswith("@@"):
            cls = "hunk"
        elif line.startswith("+"):
            cls = "add"
        elif line.startswith("-"):
            cls = "del"
        else:
            cls = "ctx"
        lines.append({"cls": cls, "text": line})

    truncated = len(lines) > MAX_DIFF_LINES
    return {"binary": False, "lines": lines[:MAX_DIFF_LINES], "truncated": truncated}


def discard(root: Path, path: str, untracked: bool) -> None:
    """Revert one data file to HEAD (or delete it if untracked)."""
    if not is_data_path(path):
        raise GitError(f"Refusing to touch non-data path: {path}")
    if untracked:
        target = (root / path).resolve()
        target.relative_to(root.resolve())  # raises if it escapes the repo
        target.unlink(missing_ok=True)
    else:
        _git(root, "restore", "--source=HEAD", "--staged", "--worktree", "--", path)


def approve(root: Path, paths: list[str], message: str) -> dict[str, Any]:
    """Commit the given data paths on main and push to origin.

    Returns a step-by-step result; commit failure raises, but sync/push
    problems are reported rather than raised so a local commit is never lost.
    """
    branch = current_branch(root)
    if branch != COMMIT_BRANCH:
        raise GitError(f"On branch '{branch}' — approvals only commit on {COMMIT_BRANCH}.")
    bad = [p for p in paths if not is_data_path(p)]
    if bad:
        raise GitError(f"Refusing to commit non-data paths: {', '.join(bad)}")
    if not paths:
        raise GitError("No files selected.")

    result: dict[str, Any] = {"pull": None, "commit": None, "push": None}

    pull = _git(root, "pull", "--ff-only", check=False)
    if pull.returncode != 0:
        result["pull"] = (pull.stderr or pull.stdout).strip().splitlines()[-1:]
        result["pull"] = result["pull"][0] if result["pull"] else "pull failed"

    _git(root, "add", "-A", "--", *paths)
    _git(root, "commit", "-m", message, "--", *paths)
    result["commit"] = _git(root, "rev-parse", "--short", "HEAD").stdout.strip()

    push = _git(root, "push", "origin", COMMIT_BRANCH, check=False)
    if push.returncode != 0:
        detail = (push.stderr or push.stdout).strip().splitlines()
        result["push"] = detail[-1] if detail else "push failed"

    return result


def push_main(root: Path) -> dict[str, Any]:
    """Push local commits on the commit branch to origin (retry after a failed
    approve push). Returns {"pull": ..., "push": ...} with None meaning success.
    """
    branch = current_branch(root)
    if branch != COMMIT_BRANCH:
        raise GitError(f"On branch '{branch}' — push only runs on {COMMIT_BRANCH}.")

    result: dict[str, Any] = {"pull": None, "push": None}

    pull = _git(root, "pull", "--ff-only", check=False)
    if pull.returncode != 0:
        detail = (pull.stderr or pull.stdout).strip().splitlines()
        result["pull"] = detail[-1] if detail else "pull failed"

    push = _git(root, "push", "origin", COMMIT_BRANCH, check=False)
    if push.returncode != 0:
        detail = (push.stderr or push.stdout).strip().splitlines()
        result["push"] = detail[-1] if detail else "push failed"

    return result


def unpushed_count(root: Path) -> int:
    """Commits on the local commit branch not yet on origin (0 when unknown)."""
    proc = _git(root, "rev-list", "--count",
                f"origin/{COMMIT_BRANCH}..{COMMIT_BRANCH}", check=False)
    try:
        return int(proc.stdout.strip())
    except ValueError:
        return 0
