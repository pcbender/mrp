from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest
import yaml

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "app" / "critic"))

from critic import catalog


def _write_release(directory: Path, slug: str, *, artist: str = "artist",
                   release_date: str | None, release_type: str = "single",
                   summary: str = "") -> None:
    release = {
        "slug": slug,
        "title": slug.replace("-", " ").title(),
        "artist_id": artist,
        "model": "album" if release_type in {"album", "ep"} else "song",
        "release_type": release_type,
        "release_date": release_date,
        "summary": summary,
    }
    (directory / f"{slug}.yaml").write_text(
        yaml.safe_dump({"release": release}, sort_keys=False), encoding="utf-8"
    )


def _write_critic_review(root: Path, review_id: str, *, summary: str,
                         status: str = "approved", track_id: str | None = None) -> None:
    (root / "out" / f"{review_id}.json").write_text(
        json.dumps({"review": {"status": status}}), encoding="utf-8"
    )
    (root / "reviews" / f"{review_id}.md").write_text(
        "\n".join([
            "---",
            f"track_id: {track_id or review_id}",
            f"summary: {json.dumps(summary)}",
            "---",
            "",
            "Full review.",
        ]),
        encoding="utf-8",
    )


@pytest.fixture
def pit_catalog(tmp_path, monkeypatch):
    releases = tmp_path / "releases"
    artists = tmp_path / "artists"
    reviews = tmp_path / "reviews"
    critic_out = tmp_path / "out"
    releases.mkdir()
    artists.mkdir()
    reviews.mkdir()
    critic_out.mkdir()
    (artists / "artist.yaml").write_text(yaml.safe_dump({"artist": {
        "id": "artist",
        "name": "Point In Time Artist",
        "bio_long": "Future Album changed everything in 2026.",
    }}))
    monkeypatch.setattr(catalog, "_RELEASES_DIR", releases)
    monkeypatch.setattr(catalog, "_ARTISTS_DIR", artists)
    monkeypatch.setattr(catalog, "_REVIEWS_DIR", reviews)
    monkeypatch.setattr(catalog, "_CRITIC_OUT_DIR", critic_out)
    return releases


@pytest.mark.parametrize("release_type", ["single", "ep", "album"])
def test_critic_context_excludes_future_catalog_for_every_release_type(
    pit_catalog: Path, release_type: str
):
    _write_release(
        pit_catalog, "past-release", release_date="2023-06-01",
        summary="Earlier work belongs in the context."
    )
    _write_release(
        pit_catalog, "target", release_date="2024-05-01", release_type=release_type,
        summary="Existing target copy must not be fed back into its own review."
    )
    _write_release(pit_catalog, "same-day", release_date="2024-05-01")
    _write_release(
        pit_catalog, "future-release", release_date="2025-01-01",
        summary="Future catalog leak."
    )
    _write_release(pit_catalog, "undated", release_date=None)
    _write_release(
        pit_catalog, "other-artist", artist="other", release_date="2024-01-01"
    )

    context = catalog.get_persona("artist", release_slug="target")

    assert "Release-date cutoff: 2024-05-01" in context
    assert "Past Release" in context
    assert "Same Day" in context
    assert "Target" in context and "[target release]" in context
    assert "Earlier work belongs in the context." in context
    assert "Future Release" not in context
    assert "Future catalog leak" not in context
    assert "Undated" not in context
    assert "Other Artist" not in context
    assert "Future Album changed everything" not in context
    assert "Existing target copy" not in context


@pytest.mark.parametrize(
    ("release_type", "review_id", "status"),
    [
        ("single", "artist--past-release", "approved"),
        ("ep", "album--artist--past-release", "publishable"),
        ("album", "album--artist--past-release", "approved"),
    ],
)
def test_prior_release_prefers_approved_critic_summary_for_every_release_type(
    pit_catalog: Path, release_type: str, review_id: str, status: str
):
    _write_release(
        pit_catalog,
        "past-release",
        release_date="2023-06-01",
        release_type=release_type,
        summary="Catalog fallback should be replaced.",
    )
    _write_release(pit_catalog, "target", release_date="2024-05-01")
    _write_critic_review(
        pit_catalog.parent,
        review_id,
        summary="The approved critic remembers this earlier release.",
        status=status,
    )

    context = catalog.get_point_in_time_context("artist", "target")

    assert "Approved critic summary: The approved critic remembers this earlier release." in context
    assert "Catalog fallback should be replaced." not in context


@pytest.mark.parametrize("status", ["pending", "draft", ""])
def test_unapproved_prior_review_falls_back_to_catalog_description(
    pit_catalog: Path, status: str
):
    _write_release(
        pit_catalog,
        "past-release",
        release_date="2023-06-01",
        summary="Stable catalog fallback.",
    )
    _write_release(pit_catalog, "target", release_date="2024-05-01")
    _write_critic_review(
        pit_catalog.parent,
        "artist--past-release",
        summary="Unapproved critic language must stay out.",
        status=status,
    )

    context = catalog.get_point_in_time_context("artist", "target")

    assert "Catalog description: Stable catalog fallback." in context
    assert "Unapproved critic language must stay out." not in context


def test_target_and_future_approved_reviews_never_enter_context(pit_catalog: Path):
    _write_release(pit_catalog, "target", release_date="2024-05-01")
    _write_release(pit_catalog, "future", release_date="2025-01-01")
    _write_critic_review(
        pit_catalog.parent,
        "artist--target",
        summary="Circular target judgment.",
    )
    _write_critic_review(
        pit_catalog.parent,
        "artist--future",
        summary="Future critical judgment.",
    )

    context = catalog.get_point_in_time_context("artist", "target")

    assert "Circular target judgment." not in context
    assert "Future critical judgment." not in context


def test_same_day_review_continuity_uses_deterministic_slug_order(pit_catalog: Path):
    _write_release(
        pit_catalog,
        "alpha",
        release_date="2024-05-01",
        summary="Alpha catalog fallback.",
    )
    _write_release(pit_catalog, "middle", release_date="2024-05-01")
    _write_release(
        pit_catalog,
        "zeta",
        release_date="2024-05-01",
        summary="Zeta catalog fallback.",
    )
    _write_critic_review(
        pit_catalog.parent,
        "artist--alpha",
        summary="Earlier same-day critical judgment.",
    )
    _write_critic_review(
        pit_catalog.parent,
        "artist--zeta",
        summary="Later same-day critical judgment.",
    )

    context = catalog.get_point_in_time_context("artist", "middle")

    assert "Approved critic summary: Earlier same-day critical judgment." in context
    assert "Later same-day critical judgment." not in context
    assert "Catalog description: Zeta catalog fallback." in context


def test_critic_context_orders_catalog_deterministically(pit_catalog: Path):
    _write_release(pit_catalog, "zeta", release_date="2024-01-01")
    _write_release(pit_catalog, "alpha", release_date="2024-01-01")
    _write_release(pit_catalog, "target", release_date="2024-05-01")

    releases = catalog.get_releases_as_of("artist", "2024-05-01")

    assert [release["slug"] for release in releases] == ["alpha", "zeta", "target"]


def test_album_contextual_pass_receives_the_same_point_in_time_boundary(pit_catalog: Path):
    from critic.album.recontextualize import _build_user_message
    from critic.album.record import AlbumRecord

    _write_release(pit_catalog, "target", release_date="2024-05-01", release_type="album")
    point_in_time = catalog.get_point_in_time_context("artist", "target")
    record = AlbumRecord(
        album_id="artist--target",
        release_slug="target",
        artist="Point In Time Artist",
        persona=point_in_time,
        tracklist=["artist--track-one"],
    )
    finding = {"review": {"verdict_tier": {"rank": 4}, "review_text": "Standalone."}}

    message = _build_user_message(record, [finding])

    assert "=== ARTIST CONTEXT (POINT IN TIME) ===" in message
    assert "Release-date cutoff: 2024-05-01" in message
    assert "Do not mention, infer, or rely on releases" in message


@pytest.mark.parametrize("release_date", [None, "not-a-date"])
def test_critic_context_rejects_missing_or_invalid_target_date(
    pit_catalog: Path, release_date: str | None
):
    _write_release(pit_catalog, "target", release_date=release_date)

    with pytest.raises(ValueError, match="Invalid point-in-time release date"):
        catalog.get_point_in_time_context("artist", "target")
