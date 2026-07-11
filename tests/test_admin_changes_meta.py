"""Unit tests for the Changes-page Phase-1 helpers.

Covers file → entity classification, publish eligibility (release must be
approved/live), the eligibility summary, and generated commit messages.
"""

import yaml

from mrp.admin.changes_meta import (
    annotate_changes,
    classify_change,
    eligibility_summary,
    generate_commit_message,
)


def _artist(root, aid, name):
    (root / "content" / "artists").mkdir(parents=True, exist_ok=True)
    (root / "content" / "artists" / f"{aid}.yaml").write_text(
        yaml.safe_dump({"artist": {"id": aid, "name": name, "visibility": "public"}}))


def _release(root, slug, title, artist_id, status):
    (root / "content" / "releases").mkdir(parents=True, exist_ok=True)
    (root / "content" / "releases" / f"{slug}.yaml").write_text(yaml.safe_dump({"release": {
        "id": slug, "slug": slug, "title": title, "artist_id": artist_id,
        "status": status, "model": "song",
    }}))


def _post(root, slug, title):
    (root / "content" / "posts").mkdir(parents=True, exist_ok=True)
    (root / "content" / "posts" / f"{slug}.yaml").write_text(
        yaml.safe_dump({"post": {"slug": slug, "title": title}}))


def _repo(tmp_path):
    _artist(tmp_path, "stab", "STAB")
    _artist(tmp_path, "pcbender", "pcbender")
    _release(tmp_path, "burn-me", "Burn Me", "stab", "live")
    _release(tmp_path, "the-hardest-gift", "The Hardest Gift", "stab", "approved")
    _release(tmp_path, "on-advent", "On the Advent of a Dream", "pcbender", "draft")
    _post(tmp_path, "hello", "Hello World")
    return tmp_path


# --- classify_change ---------------------------------------------------------

def test_classify_release_eligible_and_blocked(tmp_path):
    _repo(tmp_path)
    live = classify_change(tmp_path, "content/releases/burn-me.yaml")
    assert live["kind"] == "release" and live["eligible"] is True
    assert live["entity_title"] == "Burn Me" and live["artist_name"] == "STAB"

    draft = classify_change(tmp_path, "content/releases/on-advent.yaml")
    assert draft["eligible"] is False
    assert "draft" in draft["reason"]


def test_classify_approved_is_eligible(tmp_path):
    _repo(tmp_path)
    c = classify_change(tmp_path, "content/releases/the-hardest-gift.yaml")
    assert c["release_status"] == "approved" and c["eligible"] is True


def test_classify_artist_and_post_always_eligible(tmp_path):
    _repo(tmp_path)
    a = classify_change(tmp_path, "content/artists/stab.yaml")
    assert a["kind"] == "artist" and a["eligible"] is True and a["entity_title"] == "STAB"
    p = classify_change(tmp_path, "content/posts/hello.yaml")
    assert p["kind"] == "post" and p["eligible"] is True and p["entity_title"] == "Hello World"


def test_classify_release_asset_inherits_eligibility(tmp_path):
    _repo(tmp_path)
    # An asset path under a release folder inherits that release's status.
    c = classify_change(tmp_path, "content/assets/releases/on-advent/cover.jpg")
    assert c["kind"] == "release-asset"
    assert c["release_slug"] == "on-advent"
    assert c["eligible"] is False


def test_classify_unknown_asset_is_eligible(tmp_path):
    _repo(tmp_path)
    c = classify_change(tmp_path, "assets/source/audio/loose.wav")
    assert c["kind"] == "asset" and c["eligible"] is True


# --- eligibility_summary -----------------------------------------------------

def test_eligibility_summary_flags_blockers(tmp_path):
    _repo(tmp_path)
    changes = [{"path": p} for p in [
        "content/releases/burn-me.yaml",
        "content/releases/on-advent.yaml",
    ]]
    annotate_changes(tmp_path, changes)
    summary = eligibility_summary(changes)
    assert summary["all_eligible"] is False
    assert summary["blocker_count"] == 1
    assert "On the Advent of a Dream" in summary["blocked_releases"]


def test_eligibility_summary_all_clear(tmp_path):
    _repo(tmp_path)
    changes = [{"path": "content/releases/burn-me.yaml"},
               {"path": "content/artists/stab.yaml"}]
    annotate_changes(tmp_path, changes)
    assert eligibility_summary(changes)["all_eligible"] is True


# --- generate_commit_message -------------------------------------------------

def test_message_single_release(tmp_path):
    _repo(tmp_path)
    changes = [{"path": "content/releases/burn-me.yaml"}]
    annotate_changes(tmp_path, changes)
    assert generate_commit_message(changes) == "Update Burn Me by STAB"


def test_message_two_releases_same_artist(tmp_path):
    _repo(tmp_path)
    changes = [{"path": "content/releases/burn-me.yaml"},
               {"path": "content/releases/the-hardest-gift.yaml"}]
    annotate_changes(tmp_path, changes)
    # titles sorted: "Burn Me" and "The Hardest Gift"
    assert generate_commit_message(changes) == "Update Burn Me and The Hardest Gift by STAB"


def test_message_mixed_uses_counts(tmp_path):
    _repo(tmp_path)
    changes = [{"path": "content/releases/burn-me.yaml"},
               {"path": "content/releases/on-advent.yaml"},
               {"path": "content/artists/stab.yaml"}]
    annotate_changes(tmp_path, changes)
    assert generate_commit_message(changes) == "Update 2 releases and 1 artist profile"


def test_message_empty(tmp_path):
    assert generate_commit_message([]) == "Update site content"