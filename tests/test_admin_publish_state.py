"""Unit tests for the publish workflow state.

Covers the content-state signature (drift detection + commit invariance),
staging state persistence, verification validity vs. signature, and
affected-page URLs.
"""

import subprocess

import pytest

from mrp.admin import publish_state


def _git(root, *args):
    subprocess.run(["git", "-C", str(root), *args], check=True, capture_output=True, text=True)


def _repo(tmp_path):
    root = tmp_path / "repo"
    (root / "content" / "releases").mkdir(parents=True)
    (root / "content" / "releases" / "x.yaml").write_text("release:\n  slug: x\n")
    _git(root, "init", "-q")
    _git(root, "config", "user.email", "t@example.com")
    _git(root, "config", "user.name", "Test")
    _git(root, "add", "-A")
    _git(root, "commit", "-qm", "init")
    return root


@pytest.fixture(autouse=True)
def _isolate_state(tmp_path, monkeypatch):
    monkeypatch.setattr(publish_state, "STATE_DIR", tmp_path / "state")
    monkeypatch.setattr(publish_state, "STATE_PATH", tmp_path / "state" / "changes-workflow.json")


# --- working_signature -------------------------------------------------------

def test_signature_stable_and_nonempty_when_clean(tmp_path):
    root = _repo(tmp_path)
    sig = publish_state.working_signature(root)
    assert sig
    assert publish_state.working_signature(root) == sig


def test_signature_empty_without_managed_content(tmp_path):
    root = tmp_path / "empty"
    root.mkdir()
    _git(root, "init", "-q")
    assert publish_state.working_signature(root) == ""


def test_signature_changes_on_edit(tmp_path):
    root = _repo(tmp_path)
    sig0 = publish_state.working_signature(root)
    (root / "content" / "releases" / "x.yaml").write_text("release:\n  slug: x\n  title: A\n")
    sig1 = publish_state.working_signature(root)
    assert sig1 and sig1 != sig0
    (root / "content" / "releases" / "x.yaml").write_text("release:\n  slug: x\n  title: B\n")
    sig2 = publish_state.working_signature(root)
    assert sig2 and sig2 != sig1


def test_signature_invariant_across_commit(tmp_path):
    root = _repo(tmp_path)
    (root / "content" / "releases" / "x.yaml").write_text("release:\n  slug: x\n  title: A\n")
    (root / "content" / "releases" / "y.yaml").write_text("release:\n  slug: y\n")
    before = publish_state.working_signature(root)
    _git(root, "add", "-A")
    _git(root, "commit", "-qm", "edit + add")
    assert publish_state.working_signature(root) == before


def test_signature_delete_invariant_across_commit(tmp_path):
    root = _repo(tmp_path)
    clean = publish_state.working_signature(root)
    (root / "content" / "releases" / "x.yaml").unlink()
    deleted = publish_state.working_signature(root)
    assert deleted != clean
    _git(root, "add", "-A")
    _git(root, "commit", "-qm", "delete x")
    assert publish_state.working_signature(root) == deleted


def test_verified_state_survives_commit(tmp_path):
    root = _repo(tmp_path)
    (root / "content" / "releases" / "x.yaml").write_text("release:\n  slug: x\n  title: A\n")
    sig = publish_state.working_signature(root)
    publish_state.record_staging(root, sig, "b", "r", "passed")
    publish_state.mark_staging_verified(root, sig)
    _git(root, "add", "-A")
    _git(root, "commit", "-qm", "commit mid-ladder")
    assert publish_state.workflow_status(root)["staging_verified"] is True


# --- staging state + workflow_status ----------------------------------------

def test_record_staging_is_current(tmp_path):
    root = _repo(tmp_path)
    (root / "content" / "releases" / "x.yaml").write_text("release:\n  slug: x\n  title: A\n")
    sig = publish_state.working_signature(root)
    publish_state.record_staging(root, sig, "build-1", "reports/deployment/r.json", "passed")
    wf = publish_state.workflow_status(root)
    assert wf["staged_current"] is True
    assert wf["staging_stale"] is False
    assert wf["staging_verified"] is False
    assert wf["staging"]["build_id"] == "build-1"


def test_edit_after_staging_marks_stale(tmp_path):
    root = _repo(tmp_path)
    (root / "content" / "releases" / "x.yaml").write_text("release:\n  slug: x\n  title: A\n")
    publish_state.record_staging(root, publish_state.working_signature(root), "b", "r", "passed")
    # Further edit changes the signature → staged build no longer current.
    (root / "content" / "releases" / "x.yaml").write_text("release:\n  slug: x\n  title: C\n")
    wf = publish_state.workflow_status(root)
    assert wf["staged_current"] is False
    assert wf["staging_stale"] is True


# --- verification ------------------------------------------------------------

def test_verify_requires_matching_signature(tmp_path):
    root = _repo(tmp_path)
    (root / "content" / "releases" / "x.yaml").write_text("release:\n  slug: x\n  title: A\n")
    sig = publish_state.working_signature(root)
    publish_state.record_staging(root, sig, "b", "r", "passed")
    assert publish_state.mark_staging_verified(root, sig) is True
    assert publish_state.workflow_status(root)["staging_verified"] is True


def test_verify_rejected_for_wrong_signature(tmp_path):
    root = _repo(tmp_path)
    (root / "content" / "releases" / "x.yaml").write_text("release:\n  slug: x\n  title: A\n")
    publish_state.record_staging(root, publish_state.working_signature(root), "b", "r", "passed")
    assert publish_state.mark_staging_verified(root, "deadbeefdeadbeef") is False


def test_edit_after_verify_invalidates_it(tmp_path):
    root = _repo(tmp_path)
    (root / "content" / "releases" / "x.yaml").write_text("release:\n  slug: x\n  title: A\n")
    sig = publish_state.working_signature(root)
    publish_state.record_staging(root, sig, "b", "r", "passed")
    publish_state.mark_staging_verified(root, sig)
    (root / "content" / "releases" / "x.yaml").write_text("release:\n  slug: x\n  title: Z\n")
    assert publish_state.workflow_status(root)["staging_verified"] is False


def _stage_and_verify(root):
    """Helper: put root into a staged+verified state at its current signature."""
    sig = publish_state.working_signature(root)
    publish_state.record_staging(root, sig, "build-1", "r-stage", "passed")
    publish_state.mark_staging_verified(root, sig)
    return sig


# --- production ----------------------------------------------------------------

def test_production_verify_reached_after_staging(tmp_path):
    root = _repo(tmp_path)
    (root / "content" / "releases" / "x.yaml").write_text("release:\n  slug: x\n  title: A\n")
    sig = _stage_and_verify(root)
    assert publish_state.workflow_status(root)["production_verified"] is False
    publish_state.record_production(root, sig, "build-1", "r-deploy", "r-verify", "passed")
    assert publish_state.mark_production_verified(root, sig) is True
    assert publish_state.workflow_status(root)["production_verified"] is True


def test_edit_after_production_verify_invalidates_whole_ladder(tmp_path):
    root = _repo(tmp_path)
    (root / "content" / "releases" / "x.yaml").write_text("release:\n  slug: x\n  title: A\n")
    sig = _stage_and_verify(root)
    publish_state.record_production(root, sig, "build-1", "d", "v", "passed")
    publish_state.mark_production_verified(root, sig)
    # Any further edit invalidates staging + production verification.
    (root / "content" / "releases" / "x.yaml").write_text("release:\n  slug: x\n  title: Z\n")
    wf = publish_state.workflow_status(root)
    assert wf["staging_verified"] is False
    assert wf["production_verified"] is False
    assert wf["production_stale"] is True


def test_production_verify_rejected_for_wrong_signature(tmp_path):
    root = _repo(tmp_path)
    (root / "content" / "releases" / "x.yaml").write_text("release:\n  slug: x\n  title: A\n")
    sig = _stage_and_verify(root)
    publish_state.record_production(root, sig, "build-1", "d", "v", "passed")
    assert publish_state.mark_production_verified(root, "deadbeefdeadbeef") is False


def test_clear_state_removes_workflow(tmp_path):
    root = _repo(tmp_path)
    (root / "content" / "releases" / "x.yaml").write_text("release:\n  slug: x\n  title: A\n")
    _stage_and_verify(root)
    publish_state.clear_state(root)
    assert publish_state.load_state(root) == {}


def test_state_keyed_by_root(tmp_path):
    root = _repo(tmp_path)
    publish_state.save_state(root, {"staging": {"build_id": "b"}})
    other = tmp_path / "other"
    other.mkdir()
    assert publish_state.load_state(other) == {}
    assert publish_state.load_state(root)["staging"]["build_id"] == "b"


# --- affected_pages ----------------------------------------------------------

def test_affected_pages_builds_release_and_artist_urls():
    changes = [
        {"kind": "release", "release_slug": "burn-me", "entity_title": "Burn Me"},
        {"kind": "artist", "entity_id": "stab", "entity_title": "STAB"},
        {"kind": "release-asset", "release_slug": "burn-me", "entity_title": "Burn Me"},
    ]
    pages = publish_state.affected_pages(changes, "https://staging.example.com")
    urls = {p["url"] for p in pages}
    assert urls == {
        "https://staging.example.com/releases/burn-me/",
        "https://staging.example.com/artists/stab/",
    }
