"""Unit tests for the decoupled push helpers (gitops.push_main / unpushed_count).

Uses a local bare repo as origin so pushes are real but offline.
"""

import subprocess

import pytest

from mrp.admin import gitops


def _git(root, *args):
    subprocess.run(["git", "-C", str(root), *args], check=True, capture_output=True, text=True)


@pytest.fixture
def repo_with_origin(tmp_path):
    origin = tmp_path / "origin.git"
    origin.mkdir()
    _git(origin, "init", "-q", "--bare", "--initial-branch=main")

    root = tmp_path / "repo"
    (root / "content" / "releases").mkdir(parents=True)
    (root / "content" / "releases" / "x.yaml").write_text("release:\n  slug: x\n")
    _git(root, "init", "-q", "--initial-branch=main")
    _git(root, "config", "user.email", "t@example.com")
    _git(root, "config", "user.name", "Test")
    _git(root, "remote", "add", "origin", str(origin))
    _git(root, "add", "-A")
    _git(root, "commit", "-qm", "init")
    _git(root, "push", "-q", "-u", "origin", "main")
    return root


def test_unpushed_count_zero_when_synced(repo_with_origin):
    assert gitops.unpushed_count(repo_with_origin) == 0


def test_unpushed_count_zero_without_origin(tmp_path):
    root = tmp_path / "solo"
    (root / "content").mkdir(parents=True)
    (root / "content" / "a.yaml").write_text("a: 1\n")
    _git(root, "init", "-q", "--initial-branch=main")
    _git(root, "config", "user.email", "t@example.com")
    _git(root, "config", "user.name", "Test")
    _git(root, "add", "-A")
    _git(root, "commit", "-qm", "init")
    assert gitops.unpushed_count(root) == 0


def test_unpushed_count_after_local_commit(repo_with_origin):
    root = repo_with_origin
    (root / "content" / "releases" / "x.yaml").write_text("release:\n  slug: x\n  title: A\n")
    _git(root, "add", "-A")
    _git(root, "commit", "-qm", "local edit")
    assert gitops.unpushed_count(root) == 1


def test_push_main_pushes_pending_commits(repo_with_origin):
    root = repo_with_origin
    (root / "content" / "releases" / "x.yaml").write_text("release:\n  slug: x\n  title: A\n")
    _git(root, "add", "-A")
    _git(root, "commit", "-qm", "local edit")
    result = gitops.push_main(root)
    assert result["push"] is None
    assert gitops.unpushed_count(root) == 0


def test_push_main_refuses_off_main(repo_with_origin):
    root = repo_with_origin
    _git(root, "checkout", "-q", "-b", "topic")
    with pytest.raises(gitops.GitError):
        gitops.push_main(root)
