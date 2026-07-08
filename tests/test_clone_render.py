import html
import json
import os
import subprocess
import sys
from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parents[1]


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
    # Likewise, the native page uses the artist record's own (migrated,
    # deduplicated) image path rather than a raw wp-content passthrough URL.
    assert "/assets/migrated/9738fd064754-PCBender.png" in pcbender

    circuiting = (build_path / "artists/pcbender/circuiting/index.html").read_text()
    # circuiting was promoted from a clone-only page to a real catalog
    # release, so this legacy nested URL now resolves to the canonical
    # structured release page (isStructuredReleaseRoute in [...slug].astro)
    # instead of raw clone HTML.
    assert 'class="release-landing"' in circuiting
    assert "Circuiting" in circuiting
    assert "/assets/migrated/a4753b0ddd52-Circuiting.jpg" in circuiting

    post = (build_path / "2025/02/26/the-future-of-ai-in-music/index.html").read_text()
    # Blog posts get a dedicated post-detail layout (added after this test was
    # written) instead of the generic wp-clone-content wrapper, so they no
    # longer carry a data-clone-kind attribute.
    assert 'class="post-detail"' in post
    assert "The Future of AI in Music" in post
