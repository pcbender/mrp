import json
import os
import shutil
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def run_mrp(*args: str, cwd: Path = ROOT, site_out_root: Path | None = None) -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    if site_out_root is not None:
        env["MRP_SITE_OUT_ROOT"] = str(site_out_root)
    return subprocess.run(
        [sys.executable, "-m", "mrp.cli.main", *args],
        cwd=cwd,
        text=True,
        capture_output=True,
        check=False,
        env=env,
    )


def minimal_repo(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"
    shutil.copytree(ROOT / "content", repo / "content")
    (repo / "reports" / "build").mkdir(parents=True)
    (repo / "reports" / "validation").mkdir(parents=True)
    return repo


def test_build_creates_external_staging_artifact_and_report(tmp_path):
    out_root = tmp_path / "site-out"
    result = run_mrp("--json", "build", site_out_root=out_root)

    assert result.returncode == 0
    payload = json.loads(result.stdout)
    assert payload["status"] == "passed"
    assert payload["build_id"]
    build_path = Path(payload["build_path"])
    assert build_path.is_absolute()
    assert out_root in build_path.parents
    assert ROOT not in build_path.parents
    assert payload["manifest_path"].endswith("build-manifest.json")
    assert payload["validation_report_path"].startswith("reports/validation/")
    assert payload["file_count"] > 0
    assert (build_path / "index.html").is_file()
    assert (build_path / "licensing-custom-songs/music-licensing/index.html").is_file()
    assert (build_path / "the-future-of-ai-in-music/index.html").is_file()
    assert (build_path / "posts/index.html").is_file()
    assert (build_path / "releases/circuiting/index.html").is_file()
    sitemap = (build_path / "sitemap.xml").read_text()
    assert "https://www.maricoparecords.com/licensing-custom-songs/music-licensing/" in sitemap
    assert "https://www.maricoparecords.com/the-future-of-ai-in-music/" in sitemap
    feed = (build_path / "feed.xml").read_text()
    assert "The Future of AI in Music" in feed
    conversation = (build_path / "a-conversation-with-echo/index.html").read_text()
    assert 'href="/the-future-of-ai-in-music/"' in conversation
    assert "/2025/02/26/the-future-of-ai-in-music/" not in conversation
    licensing = (build_path / "licensing-custom-songs/music-licensing/index.html").read_text()
    assert "/assets/wp/" in licensing
    assert "https://www.maricoparecords.com/wp-content/" not in licensing
    assert "https://www.maricoparecords.com/wp-includes/" not in licensing
    licensing_parent = (build_path / "licensing-custom-songs/index.html").read_text()
    assert 'href="/licensing-custom-songs/custom-songs-for-hire/"' in licensing_parent
    streaming = (build_path / "artists/pcbender/too-blue-to-lose/index.html").read_text()
    assert "https://open.spotify.com" in streaming
    assert "https://music.apple.com" in streaming
    assert "https://music.youtube.com" in streaming
    assert Path(payload["manifest_path"]).is_file()
    assert (ROOT / payload["report_path"]).is_file()


def test_build_release_filter_passes_for_known_release(tmp_path):
    result = run_mrp("--json", "build", "--release", "circuiting", site_out_root=tmp_path / "site-out")

    assert result.returncode == 0
    payload = json.loads(result.stdout)
    assert payload["status"] == "passed"
    assert payload["release"] == "circuiting"
    assert "-circuiting" in payload["build_id"]


def test_build_blocks_on_failed_validation(tmp_path):
    repo = minimal_repo(tmp_path)

    result = run_mrp("--repo", str(repo), "--json", "build", "--release", "missing")

    assert result.returncode == 1
    payload = json.loads(result.stdout)
    assert payload["status"] == "failed"
    assert payload["stage"] == "validation"
    assert payload["validation_report_path"].startswith("reports/validation/")
    assert not (repo / "builds").exists()
    assert (repo / payload["report_path"]).is_file()


def test_build_skip_validate_reaches_static_build(tmp_path):
    repo = minimal_repo(tmp_path)

    result = run_mrp("--repo", str(repo), "--json", "build", "--skip-validate", site_out_root=tmp_path / "site-out")

    assert result.returncode == 1
    payload = json.loads(result.stdout)
    assert payload["status"] == "failed"
    assert payload["stage"] == "static_build"
    assert payload["validation_report_path"] is None


def test_build_refuses_repo_internal_output_root():
    result = run_mrp("--json", "build", site_out_root=ROOT / "builds")

    assert result.returncode == 1
    payload = json.loads(result.stdout)
    assert payload["status"] == "failed"
    assert payload["stage"] == "output_path"
    assert "inside repository" in payload["message"]
