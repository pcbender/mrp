"""Tests for band members, featuring, and track-level performer attribution.

Covers the schema additions (artist.members, release.featuring,
song.performers) and the cross-file lint pass in mrp/core/validate.py.
"""

import copy
import json
import shutil
import subprocess
import sys
from pathlib import Path

import yaml
from jsonschema import Draft202012Validator, FormatChecker


ROOT = Path(__file__).resolve().parents[1]
SCHEMA_DIR = ROOT / "mrp" / "schemas"


# --------------------------------------------------------------------------
# Helpers (mirroring tests/test_validate.py's integration style)
# --------------------------------------------------------------------------

def run_mrp(*args: str, cwd: Path = ROOT) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-m", "mrp.cli.main", *args],
        cwd=cwd,
        text=True,
        capture_output=True,
        check=False,
    )


def write_yaml(path: Path, data) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.safe_dump(data, sort_keys=False))


def minimal_repo(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"
    shutil.copytree(ROOT / "content", repo / "content")
    shutil.copytree(ROOT / "site" / "public" / "assets", repo / "site" / "public" / "assets")
    shutil.rmtree(repo / "content" / "clone", ignore_errors=True)
    (repo / "content" / "clone" / "pages").mkdir(parents=True)
    (repo / "content" / "clone" / "posts").mkdir(parents=True)
    (repo / "content" / "clone" / "assets").mkdir(parents=True)
    (repo / "reports" / "validation").mkdir(parents=True)
    return repo


def schema_errors(schema_name: str, data) -> list[str]:
    schema = json.loads((SCHEMA_DIR / schema_name).read_text())
    validator = Draft202012Validator(schema, format_checker=FormatChecker())
    return [error.message for error in validator.iter_errors(data)]


def base_artist(members=None) -> dict:
    artist = {
        "artist": {
            "id": "fourcastle",
            "name": "4Castle",
            "type": "band",
            "visibility": "public",
        }
    }
    if members is not None:
        artist["artist"]["members"] = members
    return artist


def base_release(**song_extra) -> dict:
    song = {
        "title": "Circuiting",
        "slug": "circuiting",
        "explicit": False,
        "instrumental": False,
    }
    song.update(song_extra)
    return {
        "release": {
            "id": "circuiting",
            "slug": "circuiting",
            "title": "Circuiting",
            "artist_id": "pcbender",
            "model": "song",
            "release_type": "single",
            "status": "draft",
            "release_date": "2025-02-01",
            "cover_image": "assets/releases/circuiting/cover.jpg",
            "seo": {"title": "Circuiting", "description": "Circuiting on Maricopa Records."},
            "song": song,
        }
    }


# --------------------------------------------------------------------------
# Schema: artist.members
# --------------------------------------------------------------------------

def test_artist_without_members_validates():
    assert schema_errors("artist.schema.json", base_artist()) == []


def test_artist_with_valid_members_validates():
    members = [
        {"slug": "raven-cortez", "name": "Raven Cortez", "roles": ["lead guitar", "vocals"],
         "status": "current", "display_order": 1},
        {"slug": "mack-bishop", "name": "Malcolm \"Mack\" Bishop"},
    ]
    assert schema_errors("artist.schema.json", base_artist(members)) == []


def test_member_missing_slug_fails():
    assert schema_errors("artist.schema.json", base_artist([{"name": "No Slug"}]))


def test_member_missing_name_fails():
    assert schema_errors("artist.schema.json", base_artist([{"slug": "no-name"}]))


def test_member_bad_slug_pattern_fails():
    assert schema_errors("artist.schema.json", base_artist([{"slug": "Bad Slug", "name": "X"}]))


def test_member_unknown_field_fails():
    bad = [{"slug": "raven-cortez", "name": "Raven", "instrument": "guitar"}]
    assert schema_errors("artist.schema.json", base_artist(bad))


# --------------------------------------------------------------------------
# Schema: release.featuring and song.performers
# --------------------------------------------------------------------------

def test_release_with_featuring_and_performers_validates():
    release = base_release(
        featuring=["stab"],
        performers=[
            {"member": "raven-cortez", "role": "lead vocals"},
            {"artist": "stab", "role": "vocals", "note": "guest hook"},
        ],
    )
    release["release"]["featuring"] = ["stab"]
    assert schema_errors("release.schema.json", release) == []


def test_performer_with_both_member_and_artist_fails():
    release = base_release(performers=[{"member": "raven-cortez", "artist": "stab", "role": "vocals"}])
    assert schema_errors("release.schema.json", release)


def test_performer_with_neither_member_nor_artist_fails():
    release = base_release(performers=[{"role": "vocals"}])
    assert schema_errors("release.schema.json", release)


def test_performer_missing_role_fails():
    release = base_release(performers=[{"member": "raven-cortez"}])
    assert schema_errors("release.schema.json", release)


# --------------------------------------------------------------------------
# Cross-file lint pass (mrp validate)
# --------------------------------------------------------------------------

def test_valid_featuring_and_member_references_pass(tmp_path):
    repo = minimal_repo(tmp_path)
    release = base_release(performers=[{"member": "raven-cortez", "role": "lead vocals"}])
    release["release"]["artist_id"] = "4castle"
    release["release"]["featuring"] = ["stab"]
    write_yaml(repo / "content/releases/circuiting.yaml", release)

    result = run_mrp("--repo", str(repo), "--json", "validate")

    assert result.returncode == 0, result.stdout
    assert json.loads(result.stdout)["status"] == "passed"


def test_unknown_featuring_id_fails(tmp_path):
    repo = minimal_repo(tmp_path)
    release = base_release()
    release["release"]["featuring"] = ["nobody"]
    write_yaml(repo / "content/releases/circuiting.yaml", release)

    result = run_mrp("--repo", str(repo), "--json", "validate")

    assert result.returncode == 1
    payload = json.loads(result.stdout)
    assert any(error["field"] == "release.featuring.0" for error in payload["errors"])


def test_unknown_performer_member_slug_fails(tmp_path):
    repo = minimal_repo(tmp_path)
    release = base_release(performers=[{"member": "ghost", "role": "vocals"}])
    release["release"]["artist_id"] = "4castle"
    write_yaml(repo / "content/releases/circuiting.yaml", release)

    result = run_mrp("--repo", str(repo), "--json", "validate")

    assert result.returncode == 1
    payload = json.loads(result.stdout)
    assert any(error["field"] == "release.song.performers.0.member" for error in payload["errors"])


def test_unknown_performer_artist_fails(tmp_path):
    repo = minimal_repo(tmp_path)
    release = base_release(performers=[{"artist": "noone", "role": "vocals"}])
    write_yaml(repo / "content/releases/circuiting.yaml", release)

    result = run_mrp("--repo", str(repo), "--json", "validate")

    assert result.returncode == 1
    payload = json.loads(result.stdout)
    assert any(error["field"] == "release.song.performers.0.artist" for error in payload["errors"])


def test_duplicate_member_slugs_fail(tmp_path):
    repo = minimal_repo(tmp_path)
    artist = yaml.safe_load((repo / "content/artists/4castle.yaml").read_text())
    members = artist["artist"]["members"]
    duplicated = copy.deepcopy(members[0])
    members.append(duplicated)  # same slug as members[0]
    write_yaml(repo / "content/artists/4castle.yaml", artist)

    result = run_mrp("--repo", str(repo), "--json", "validate")

    assert result.returncode == 1
    payload = json.loads(result.stdout)
    assert any(error["field"].endswith(".slug") and "Duplicate member slug" in error["message"]
               for error in payload["errors"])


def test_member_slug_valid_only_for_owning_artist(tmp_path):
    """A member slug resolves only within the release's own artist_id."""
    repo = minimal_repo(tmp_path)
    # raven-cortez is a 4castle member; a pcbender release cannot reference it.
    release = base_release(performers=[{"member": "raven-cortez", "role": "vocals"}])
    release["release"]["artist_id"] = "pcbender"
    write_yaml(repo / "content/releases/circuiting.yaml", release)

    result = run_mrp("--repo", str(repo), "--json", "validate")

    assert result.returncode == 1
    payload = json.loads(result.stdout)
    assert any(error["field"] == "release.song.performers.0.member" for error in payload["errors"])


# --------------------------------------------------------------------------
# Regression: real content stays green (zero-migration goal)
# --------------------------------------------------------------------------

def test_real_content_validates_with_members():
    result = run_mrp("--json", "validate")

    assert result.returncode == 0, result.stdout
    assert json.loads(result.stdout)["status"] == "passed"
