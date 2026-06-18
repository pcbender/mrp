import json
import os
import subprocess
import sys
from pathlib import Path


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
    assert "mystique" in pcbender
    assert "wp-block-stackable-column" in pcbender
    assert "/assets/wp/wp-content/uploads/2025/02/PCBender.png" in pcbender

    circuiting = (build_path / "artists/pcbender/circuiting/index.html").read_text()
    assert "data-clone-kind=\"release_page\"" in circuiting
    assert "Circuiting is not just an album" in circuiting
    assert "/assets/wp/wp-content/uploads/2025/02/Circuiting.jpg" in circuiting

    post = (build_path / "2025/02/26/the-future-of-ai-in-music/index.html").read_text()
    assert "data-clone-kind=\"blog_post\"" in post
    assert "The Future of AI in Music" in post
