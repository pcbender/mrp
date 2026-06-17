import json
import shutil
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def run_mrp(*args: str, cwd: Path = ROOT) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-m", "mrp.cli.main", *args],
        cwd=cwd,
        text=True,
        capture_output=True,
        check=False,
    )


def minimal_repo(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"
    shutil.copytree(ROOT / "content", repo / "content")
    (repo / "reports" / "build").mkdir(parents=True)
    (repo / "reports" / "validation").mkdir(parents=True)
    return repo


def test_build_creates_staging_artifact_and_report():
    result = run_mrp("--json", "build")

    assert result.returncode == 0
    payload = json.loads(result.stdout)
    assert payload["status"] == "passed"
    assert payload["build_id"]
    assert payload["build_path"].startswith("builds/staging/")
    assert payload["manifest_path"].endswith("build-manifest.json")
    assert payload["validation_report_path"].startswith("reports/validation/")
    assert payload["file_count"] > 0
    assert (ROOT / payload["build_path"] / "index.html").is_file()
    assert (ROOT / payload["build_path"] / "licensing-custom-songs/music-licensing/index.html").is_file()
    assert (ROOT / payload["build_path"] / "the-future-of-ai-in-music/index.html").is_file()
    assert (ROOT / payload["build_path"] / "posts/index.html").is_file()
    assert (ROOT / payload["build_path"] / "releases/circuiting/index.html").is_file()
    sitemap = (ROOT / payload["build_path"] / "sitemap.xml").read_text()
    assert "https://www.maricoparecords.com/licensing-custom-songs/music-licensing/" in sitemap
    assert "https://www.maricoparecords.com/the-future-of-ai-in-music/" in sitemap
    feed = (ROOT / payload["build_path"] / "feed.xml").read_text()
    assert "The Future of AI in Music" in feed
    conversation = (ROOT / payload["build_path"] / "a-conversation-with-echo/index.html").read_text()
    assert 'href="/the-future-of-ai-in-music/"' in conversation
    assert "/2025/02/26/the-future-of-ai-in-music/" not in conversation
    licensing = (ROOT / payload["build_path"] / "licensing-custom-songs/music-licensing/index.html").read_text()
    assert "/assets/migrated/" in licensing
    assert "https://www.maricoparecords.com/wp-content/uploads" not in licensing
    streaming = (ROOT / payload["build_path"] / "artists/pcbender/too-blue-to-lose/index.html").read_text()
    assert "https://open.spotify.com" in streaming
    assert "https://music.apple.com" in streaming
    assert "https://music.youtube.com" in streaming
    assert (ROOT / payload["manifest_path"]).is_file()
    assert (ROOT / payload["report_path"]).is_file()


def test_build_release_filter_passes_for_known_release():
    result = run_mrp("--json", "build", "--release", "circuiting")

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

    result = run_mrp("--repo", str(repo), "--json", "build", "--skip-validate")

    assert result.returncode == 1
    payload = json.loads(result.stdout)
    assert payload["status"] == "failed"
    assert payload["stage"] == "static_build"
    assert payload["validation_report_path"] is None
