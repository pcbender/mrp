import html
import json
import os
import subprocess
import sys
from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parents[1]


def public_url(path: str) -> str:
    """The site-root URL a content record's image path renders as.

    Artist records store `/assets/…` while release records store
    `site/public/assets/…`; the built page always uses the site-root form.

    Rejects an empty path rather than returning "/", which would be trivially
    present in any page and turn the caller's assertion into a no-op.
    """
    url = "/" + str(path or "").strip().replace("site/public/", "", 1).lstrip("/")
    assert len(url) > 1, f"record has no usable image path: {path!r}"
    return url


def run_mrp(*args: str, site_out_root: Path) -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    env["MRP_SITE_OUT_ROOT"] = str(site_out_root)
    return subprocess.run(
        [sys.executable, "-m", "mrp.cli.main", *args],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
        env=env,
    )


def test_build_renders_wxr_clone_artist_release_and_blog_pages(tmp_path):
    result = run_mrp("--json", "build", site_out_root=tmp_path / "site-out")

    assert result.returncode == 0
    payload = json.loads(result.stdout)
    build_path = Path(payload["build_path"])
    assert build_path.is_absolute()

    pcbender = (build_path / "artists/pcbender/index.html").read_text()
    # pcbender is a promoted artist now, not a clone fallback: the native
    # artist page renders the record's curated copy (promo_blurb, falling back
    # to bio_long — mirroring [slug].astro), so assert a snippet taken from
    # the live record rather than pinning prose that drifts editorially.
    artist = yaml.safe_load((ROOT / "content/artists/pcbender.yaml").read_text())["artist"]
    bio_text = artist.get("promo_blurb") or artist.get("bio_long") or artist["bio_short"]
    bio_snippet = html.escape(bio_text.split("\n")[0].split(".")[0], quote=False)
    assert bio_snippet in pcbender
    # Raw WP block markup must not leak through (it did, pre-promotion, when
    # this page was clone-rendered).
    assert "wp-block-stackable-column" not in pcbender
    # Likewise, the native page uses the artist record's own image path rather
    # than a raw wp-content passthrough URL. Derived from the record for the
    # same reason as the bio above: an artist's image is content and moves --
    # the identity-refresh workflow replaces a migrated WP image with a
    # generated one, which is a normal edit, not a regression. Pinning the
    # filename made this test fail every time an artist's portrait was
    # refreshed. What must stay true is the two assertions below.
    assert public_url(artist["image"]) in pcbender
    assert "wp-content" not in pcbender

    circuiting = (build_path / "artists/pcbender/circuiting/index.html").read_text()
    # circuiting was promoted from a clone-only page to a real catalog
    # release, so this legacy nested URL now resolves to the canonical
    # structured release page (isStructuredReleaseRoute in [...slug].astro)
    # instead of raw clone HTML.
    assert 'class="release-landing"' in circuiting
    assert "Circuiting" in circuiting
    # Derived rather than pinned, for the same reason as the artist image: a
    # release cover is content and can be regenerated. This one still happens
    # to be the migrated asset.
    release = yaml.safe_load((ROOT / "content/releases/circuiting.yaml").read_text())["release"]
    assert public_url(release["cover_image"]) in circuiting
    assert "wp-content" not in circuiting

    post = (build_path / "2025/02/26/the-future-of-ai-in-music/index.html").read_text()
    # Blog posts get a dedicated post-detail layout (added after this test was
    # written) instead of the generic wp-clone-content wrapper, so they no
    # longer carry a data-clone-kind attribute.
    assert 'class="post-detail"' in post
    assert "The Future of AI in Music" in post
