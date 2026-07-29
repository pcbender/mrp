import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parents[1]


def site_out_root(repo: Path) -> Path:
    return repo.parent / "site-out"


def staging_path(repo: Path) -> Path:
    return site_out_root(repo) / "staging"


def staged_cover_path(repo: Path, release_id: str = "circuiting") -> Path:
    for extension in ("json", "yaml", "yml"):
        path = repo / "content" / "releases" / f"{release_id}.{extension}"
        if not path.exists():
            continue
        data = json.loads(path.read_text()) if extension == "json" else yaml.safe_load(path.read_text())
        cover = data["release"]["cover_image"]
        return staging_path(repo) / cover.removeprefix("site/public/")
    raise AssertionError(f"Missing fixture release: {release_id}")


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


def verified_repo(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"
    target = staging_path(repo)
    shutil.copytree(ROOT / "content", repo / "content")
    for name in ["artists", "releases", "pages", "posts"]:
        shutil.rmtree(repo / "content" / name)
        (repo / "content" / name).mkdir()
    shutil.copy2(ROOT / "content/artists/pcbender.yaml", repo / "content/artists/pcbender.yaml")
    shutil.copy2(ROOT / "content/releases/circuiting.yaml", repo / "content/releases/circuiting.yaml")
    (repo / "deploy").mkdir(parents=True)
    (repo / "reports" / "verification").mkdir(parents=True)
    target.mkdir(parents=True)

    (repo / "deploy" / "targets.yaml").write_text(
        yaml.safe_dump(
            {
                "targets": {
                    "local-staging": {
                        "type": "local",
                        "environment": "staging",
                        "path": "staging",
                        "require_marker": True,
                    }
                }
            },
            sort_keys=False,
        )
    )
    (target / ".allow-deploy").write_text("MARICOPA_RECORDS_DEPLOY_TARGET=staging\n")
    write_file(target / "index.html", '<a href="/artists/pcbender/">PCBender</a>\n')
    write_file(target / "artists/index.html", '<a href="/artists/pcbender/">PCBender</a>\n')
    write_file(target / "artists/pcbender/index.html", '<a href="/releases/circuiting/">Circuiting</a>\n')
    write_file(target / "releases/index.html", '<a href="/releases/circuiting/">Circuiting</a>\n')
    cover_path = staged_cover_path(repo)
    cover_url = f"/{cover_path.relative_to(target).as_posix()}"
    write_file(target / "releases/circuiting/index.html", f'<img src="{cover_url}">\n')
    write_file(cover_path, "image\n")
    write_file(target / "sitemap.xml", "<urlset></urlset>\n")
    write_file(target / "feed.xml", "<rss></rss>\n")
    return repo


def write_file(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)


def add_published_track_video(repo: Path, *, opt_in: bool = True) -> tuple[Path, Path]:
    release_path = repo / "content/releases/circuiting.yaml"
    record = yaml.safe_load(release_path.read_text(encoding="utf-8"))
    release = record["release"]
    track = release["tracks"][0]
    video_url = "/media/music-videos/pcbender--conductor/hash/video.mp4"
    poster_url = "/media/music-videos/pcbender--conductor/hash/poster.jpg"
    track["music_video"] = {
        "project": "assets/source/video/pcbender--conductor/project.yaml",
        "status": "published",
        "opt_in": opt_in,
        "public_url": video_url,
        "poster": poster_url,
    }
    release_path.write_text(yaml.safe_dump(record, sort_keys=False), encoding="utf-8")
    target = staging_path(repo)
    page = target / "releases/circuiting/conductor/index.html"
    video = target / video_url.removeprefix("/")
    poster = target / poster_url.removeprefix("/")
    if opt_in:
        write_file(
            page,
            f'<video controls src="{video_url}" poster="{poster_url}"></video>\n',
        )
        write_file(video, "video\n")
        write_file(poster, "poster\n")
    else:
        write_file(page, "<p>Public video is opted out.</p>\n")
    return video, poster


def test_verify_staging_passes_for_valid_local_target(tmp_path):
    repo = verified_repo(tmp_path)

    result = run_mrp("--repo", str(repo), "--json", "verify", "--target", "staging", site_out_root=site_out_root(repo))

    assert result.returncode == 0
    payload = json.loads(result.stdout)
    assert payload["status"] == "passed"
    assert payload["target"] == "local-staging"
    assert payload["summary"]["errors"] == 0
    assert (repo / payload["report_path"]).is_file()


def test_verify_missing_release_page_fails(tmp_path):
    repo = verified_repo(tmp_path)
    (staging_path(repo) / "releases/circuiting/index.html").unlink()

    result = run_mrp("--repo", str(repo), "--json", "verify", "--target", "staging", site_out_root=site_out_root(repo))

    assert result.returncode == 1
    payload = json.loads(result.stdout)
    assert payload["status"] == "failed"
    assert any("releases/circuiting/index.html" in error["message"] for error in payload["errors"])


def test_verify_missing_cover_image_fails(tmp_path):
    repo = verified_repo(tmp_path)
    cover_path = staged_cover_path(repo)
    cover_path.unlink()

    result = run_mrp("--repo", str(repo), "--json", "verify", "--target", "staging", site_out_root=site_out_root(repo))

    assert result.returncode == 1
    payload = json.loads(result.stdout)
    assert payload["status"] == "failed"
    expected = cover_path.relative_to(staging_path(repo)).as_posix()
    assert any(expected in error["message"] for error in payload["errors"])


def test_verify_opted_in_music_video_player_and_media(tmp_path):
    repo = verified_repo(tmp_path)
    add_published_track_video(repo)

    result = run_mrp(
        "--repo",
        str(repo),
        "--json",
        "verify",
        "--target",
        "staging",
        site_out_root=site_out_root(repo),
    )

    assert result.returncode == 0
    payload = json.loads(result.stdout)
    checks = [item for item in payload["checks"] if item["name"] == "music_videos"]
    assert checks == [{"name": "music_videos", "status": "passed", "checked": 1}]


def test_verify_missing_opted_in_music_video_fails(tmp_path):
    repo = verified_repo(tmp_path)
    video, _poster = add_published_track_video(repo)
    video.unlink()

    result = run_mrp(
        "--repo",
        str(repo),
        "--json",
        "verify",
        "--target",
        "staging",
        site_out_root=site_out_root(repo),
    )

    assert result.returncode == 1
    payload = json.loads(result.stdout)
    assert any(error["field"] == "music_video.public_url" for error in payload["errors"])


def test_verify_opted_out_music_video_requires_no_player_or_media(tmp_path):
    repo = verified_repo(tmp_path)
    video, poster = add_published_track_video(repo, opt_in=False)

    result = run_mrp(
        "--repo",
        str(repo),
        "--json",
        "verify",
        "--target",
        "staging",
        site_out_root=site_out_root(repo),
    )

    assert result.returncode == 0
    assert not video.exists()
    assert not poster.exists()


def test_verify_placeholder_token_fails(tmp_path):
    repo = verified_repo(tmp_path)
    write_file(staging_path(repo) / "about-us/index.html", "TODO\n")

    result = run_mrp("--repo", str(repo), "--json", "verify", "--target", "staging", site_out_root=site_out_root(repo))

    assert result.returncode == 1
    payload = json.loads(result.stdout)
    assert payload["status"] == "failed"
    assert any(error["field"] == "placeholder" for error in payload["errors"])


def test_verify_ignores_placeholder_tokens_in_mirrored_wordpress_assets(tmp_path):
    repo = verified_repo(tmp_path)
    write_file(staging_path(repo) / "assets/wp/wp-content/themes/anima-plus/shortcodes.js", "/* TODO upstream */\n")

    result = run_mrp("--repo", str(repo), "--json", "verify", "--target", "staging", site_out_root=site_out_root(repo))

    assert result.returncode == 0
    payload = json.loads(result.stdout)
    assert payload["status"] == "passed"


def test_verify_ignores_protocol_relative_external_links(tmp_path):
    repo = verified_repo(tmp_path)
    write_file(staging_path(repo) / "about-us/index.html", '<link rel="stylesheet" href="//fonts.googleapis.com/css?family=Raleway">')

    result = run_mrp("--repo", str(repo), "--json", "verify", "--target", "staging", site_out_root=site_out_root(repo))

    assert result.returncode == 0
    payload = json.loads(result.stdout)
    assert payload["status"] == "passed"


def migrated_verified_repo(tmp_path: Path) -> Path:
    repo = verified_repo(tmp_path)
    write_file(
        repo / "content/pages/music.yaml",
        yaml.safe_dump(
            {
                "page": {
                    "id": "music",
                    "slug": "music",
                    "title": "Music",
                    "normalized_path": "/music/",
                    "content_html": "<p>Music</p>",
                }
            },
            sort_keys=False,
        ),
    )
    write_file(
        repo / "content/posts/news.yaml",
        yaml.safe_dump(
            {
                "post": {
                    "id": "news",
                    "slug": "news",
                    "title": "News",
                    "normalized_path": "/news/",
                    "content_html": "<p>News</p>",
                }
            },
            sort_keys=False,
        ),
    )
    write_file(
        repo / "content/redirects.yaml",
        yaml.safe_dump(
            {
                "redirects": [
                    {
                        "source_path": "/2025/02/26/news/",
                        "normalized_path": "/2025/02/26/news/",
                        "status": "normalized",
                    }
                ]
            },
            sort_keys=False,
        ),
    )
    write_file(
        repo / "content/assets/manifest.yaml",
        yaml.safe_dump(
            {
                "assets": [
                    {
                        "id": "migrated-cover",
                        "path": "site/public/assets/migrated/cover.jpg",
                        "type": "image",
                        "usage": ["migrated_content"],
                        "required": True,
                        "alt": None,
                    }
                ]
            },
            sort_keys=False,
        ),
    )
    write_file(staging_path(repo) / "music/index.html", "<p>Music</p>\n")
    write_file(staging_path(repo) / "news/index.html", "<p>News</p>\n")
    write_file(staging_path(repo) / "2025/02/26/news/index.html", "<p>News alias</p>\n")
    write_file(staging_path(repo) / "assets/migrated/cover.jpg", "image\n")
    return repo


def test_verify_migration_surface_passes_for_routes_assets_and_aliases(tmp_path):
    repo = migrated_verified_repo(tmp_path)

    result = run_mrp("--repo", str(repo), "--json", "verify", "--target", "staging", site_out_root=site_out_root(repo))

    assert result.returncode == 0
    payload = json.loads(result.stdout)
    assert payload["status"] == "passed"
    assert payload["migration"]["enabled"] is True
    assert payload["migration"]["pages"] == 1
    assert payload["migration"]["posts"] == 1
    assert payload["migration"]["routes_checked"] == 3
    assert payload["migration"]["asset_records_checked"] == 1


def test_verify_missing_migrated_route_fails(tmp_path):
    repo = migrated_verified_repo(tmp_path)
    (staging_path(repo) / "music/index.html").unlink()

    result = run_mrp("--repo", str(repo), "--json", "verify", "--target", "staging", site_out_root=site_out_root(repo))

    assert result.returncode == 1
    payload = json.loads(result.stdout)
    assert payload["status"] == "failed"
    assert any("music/index.html" in error["message"] for error in payload["errors"])


def test_verify_missing_migrated_asset_fails(tmp_path):
    repo = migrated_verified_repo(tmp_path)
    (staging_path(repo) / "assets/migrated/cover.jpg").unlink()

    result = run_mrp("--repo", str(repo), "--json", "verify", "--target", "staging", site_out_root=site_out_root(repo))

    assert result.returncode == 1
    payload = json.loads(result.stdout)
    assert payload["status"] == "failed"
    assert any("assets/migrated/cover.jpg" in error["message"] for error in payload["errors"])


def test_verify_excluded_migration_path_fails(tmp_path):
    repo = migrated_verified_repo(tmp_path)
    write_file(staging_path(repo) / "cart/index.html", "<p>Cart</p>\n")

    result = run_mrp("--repo", str(repo), "--json", "verify", "--target", "staging", site_out_root=site_out_root(repo))

    assert result.returncode == 1
    payload = json.loads(result.stdout)
    assert payload["status"] == "failed"
    assert any(error["field"] == "migration.excluded_path" for error in payload["errors"])


def clone_verified_repo(tmp_path: Path) -> Path:
    repo = verified_repo(tmp_path)
    pages_dir = repo / "content" / "clone" / "pages"
    posts_dir = repo / "content" / "clone" / "posts"
    assets_dir = repo / "content" / "clone" / "assets"
    shutil.rmtree(pages_dir, ignore_errors=True)
    shutil.rmtree(posts_dir, ignore_errors=True)
    shutil.rmtree(assets_dir, ignore_errors=True)
    pages_dir.mkdir(parents=True)
    posts_dir.mkdir(parents=True)
    assets_dir.mkdir(parents=True)
    write_file(
        pages_dir / "artists-pcbender.yaml",
        yaml.safe_dump(
            {
                "clone": {
                    "id": "artists-pcbender",
                    "kind": "artist_page",
                    "title": "PCBender",
                    "route": {"canonical_path": "/artists/pcbender/", "aliases": []},
                    "content_html": "<p>mystique</p>",
                }
            },
            sort_keys=False,
        ),
    )
    write_file(
        pages_dir / "artists-pcbender-circuiting.yaml",
        yaml.safe_dump(
            {
                "clone": {
                    "id": "artists-pcbender-circuiting",
                    "kind": "release_page",
                    "title": "Circuiting",
                    "route": {"canonical_path": "/artists/pcbender/circuiting/", "aliases": []},
                    "content_html": "<p>Circuiting is not just an album</p>",
                }
            },
            sort_keys=False,
        ),
    )
    write_file(
        assets_dir / "manifest.yaml",
        yaml.safe_dump(
            {
                "clone_assets": [
                    {
                        "id": "wp-pcbender",
                        "source_url": "https://www.maricoparecords.com/wp-content/uploads/pcbender.png",
                        "local_path": "site/public/assets/wp/wp-content/uploads/pcbender.png",
                        "status": "mirrored",
                        "required": True,
                    }
                ]
            },
            sort_keys=False,
        ),
    )
    write_file(
        staging_path(repo) / "artists/pcbender/index.html",
        '<article class="wp-clone-content" data-clone-kind="artist_page">mystique<img src="/assets/wp/wp-content/uploads/pcbender.png"></article>',
    )
    write_file(
        staging_path(repo) / "artists/pcbender/circuiting/index.html",
        '<article class="wp-clone-content" data-clone-kind="release_page">Circuiting is not just an album</article>',
    )
    write_file(staging_path(repo) / "assets/wp/wp-content/uploads/pcbender.png", "image\n")
    return repo


def test_verify_clone_surface_passes_for_routes_assets_and_markers(tmp_path):
    repo = clone_verified_repo(tmp_path)

    result = run_mrp("--repo", str(repo), "--json", "verify", "--target", "staging", site_out_root=site_out_root(repo))

    assert result.returncode == 0
    payload = json.loads(result.stdout)
    assert payload["status"] == "passed"
    assert payload["clone"]["enabled"] is True
    assert payload["clone"]["pages"] == 2
    assert payload["clone"]["posts"] == 0
    assert payload["clone"]["routes_checked"] == 2
    assert payload["clone"]["asset_records_checked"] == 1
    assert payload["clone"]["rendered_wp_asset_refs_checked"] == 1
    # CLONE_KNOWN_MARKERS is intentionally empty: the original marker pages
    # are native now and their copy drifts editorially.
    assert payload["clone"]["known_markers_checked"] == 0


def test_verify_missing_clone_route_fails(tmp_path):
    repo = clone_verified_repo(tmp_path)
    (staging_path(repo) / "artists/pcbender/circuiting/index.html").unlink()

    result = run_mrp("--repo", str(repo), "--json", "verify", "--target", "staging", site_out_root=site_out_root(repo))

    assert result.returncode == 1
    payload = json.loads(result.stdout)
    assert payload["status"] == "failed"
    assert any("artists/pcbender/circuiting/index.html" in error["message"] for error in payload["errors"])


def test_verify_missing_rendered_clone_asset_fails(tmp_path):
    repo = clone_verified_repo(tmp_path)
    (staging_path(repo) / "assets/wp/wp-content/uploads/pcbender.png").unlink()

    result = run_mrp("--repo", str(repo), "--json", "verify", "--target", "staging", site_out_root=site_out_root(repo))

    assert result.returncode == 1
    payload = json.loads(result.stdout)
    assert payload["status"] == "failed"
    assert any(error["field"] == "clone.asset" for error in payload["errors"])


def test_verify_known_marker_mechanism_flags_missing_text(tmp_path, monkeypatch):
    # CLONE_KNOWN_MARKERS ships empty, so exercise the mechanism with an
    # injected marker instead of pinning live page prose.
    from mrp.core import verify as verify_module

    marker = {
        "route": "/artists/pcbender/",
        "marker": "mystique",
        "description": "pcbender artist page",
    }
    monkeypatch.setattr(verify_module, "CLONE_KNOWN_MARKERS", [marker])
    target = tmp_path / "staging"
    write_file(target / "artists/pcbender/index.html", '<article class="wp-clone-content">PCBender</article>')

    result = {"checks": [], "errors": []}
    checked = verify_module.check_clone_known_markers(result, target)

    assert checked == 1
    assert any(error["field"] == "clone.marker" for error in result["errors"])

    write_file(target / "artists/pcbender/index.html", '<article class="wp-clone-content">mystique</article>')
    result = {"checks": [], "errors": []}
    verify_module.check_clone_known_markers(result, target)
    assert result["errors"] == []


def test_verify_excluded_clone_path_fails(tmp_path):
    repo = clone_verified_repo(tmp_path)
    write_file(staging_path(repo) / "checkout/index.html", "<p>Checkout</p>\n")

    result = run_mrp("--repo", str(repo), "--json", "verify", "--target", "staging", site_out_root=site_out_root(repo))

    assert result.returncode == 1
    payload = json.loads(result.stdout)
    assert payload["status"] == "failed"
    assert any(error["field"] == "clone.excluded_path" for error in payload["errors"])


def test_withdrawn_releases_are_not_required_to_have_pages(tmp_path: Path) -> None:
    """Verification must ask the same question the site build asks.

    The site renders only publishable statuses, so an archived release has no
    page by design. The checks used to skip just ``draft``, which turned a
    correctly withdrawn release into "Missing required file" and failed
    production verification for behaving properly.
    """
    from mrp.core.verify import check_cover_images, check_music_videos, check_release_pages

    build = tmp_path / "build"
    (build / "releases" / "live-one").mkdir(parents=True)
    (build / "releases" / "live-one" / "index.html").write_text("<html></html>")
    cover = build / "images" / "live-one.jpg"
    cover.parent.mkdir(parents=True)
    cover.write_bytes(b"jpeg")

    releases = [
        {
            "id": "live-one",
            "slug": "live-one",
            "status": "live",
            "cover_image": "site/public/images/live-one.jpg",
        },
        # Withdrawn: the build deliberately contains neither page nor cover.
        {
            "id": "gone",
            "slug": "gone",
            "status": "archived",
            "cover_image": "site/public/images/gone.jpg",
        },
        {"id": "wip", "slug": "wip", "status": "draft", "cover_image": None},
    ]

    for check in (check_release_pages, check_cover_images):
        result: dict = {"checks": [], "errors": []}
        check(result, build, releases)
        assert result["errors"] == [], f"{check.__name__} flagged a withdrawn release"

    result = {"checks": [], "errors": []}
    check_music_videos(result, build, releases)
    assert result["errors"] == []


def test_published_releases_are_still_required_to_have_pages(tmp_path: Path) -> None:
    """Narrowing the status set must not stop it catching a real omission."""
    from mrp.core.verify import check_release_pages

    build = tmp_path / "build"
    build.mkdir()
    result: dict = {"checks": [], "errors": []}

    check_release_pages(result, build, [{"id": "x", "slug": "x", "status": "live"}])

    assert [error["message"] for error in result["errors"]] == [
        "Missing required file: releases/x/index.html"
    ]
