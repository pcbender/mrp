import fcntl
import json
from pathlib import Path

from mrp.core.prune import prune_outputs


def make_environment(tmp_path: Path, monkeypatch, build_ids: list[str], cache_ids: list[str] | None = None) -> tuple[Path, Path, Path]:
    repo = tmp_path / "repo"
    (repo / "reports" / "deployment").mkdir(parents=True)
    out_root = tmp_path / "site-out"
    for build_id in build_ids:
        build_dir = out_root / "builds" / "staging" / build_id
        build_dir.mkdir(parents=True)
        (build_dir / "index.html").write_text("<html></html>\n")
    for cache_id in cache_ids if cache_ids is not None else build_ids:
        cache_dir = out_root / "cache" / cache_id / "site"
        cache_dir.mkdir(parents=True)
        (cache_dir / "astro.config.mjs").write_text("export default {}\n")
    history = tmp_path / "nas" / "mrp-history"
    history.mkdir(parents=True)
    (history / ".mrp-history-root").touch()
    monkeypatch.setenv("MRP_SITE_OUT_ROOT", str(out_root))
    monkeypatch.setenv("MRP_HISTORY_ROOT", str(history))
    return repo, out_root, history


def write_deployment_report(repo: Path, name: str, target: str, build_id: str, status: str = "passed") -> None:
    report = {"target": target, "build_id": build_id, "status": status}
    (repo / "reports" / "deployment" / f"{name}.json").write_text(json.dumps(report))


def test_prune_moves_old_builds_and_caches_to_history(tmp_path, monkeypatch):
    build_ids = [f"2026070{i}T000000000000Z-site" for i in range(1, 8)]
    repo, out_root, history = make_environment(tmp_path, monkeypatch, build_ids)

    result = prune_outputs(repo, keep=5)

    assert result["status"] == "passed"
    assert result["moved_builds"] == build_ids[:2]
    assert result["moved_caches"] == build_ids[:2]
    for build_id in build_ids[:2]:
        assert not (out_root / "builds" / "staging" / build_id).exists()
        assert (history / "builds" / "staging" / build_id / "index.html").is_file()
        assert (history / "cache" / build_id / "site" / "astro.config.mjs").is_file()
    for build_id in build_ids[2:]:
        assert (out_root / "builds" / "staging" / build_id).is_dir()
        assert (out_root / "cache" / build_id).is_dir()
    assert (repo / result["report_path"]).is_file()


def test_prune_protects_deployed_builds_beyond_keep_window(tmp_path, monkeypatch):
    build_ids = [f"2026070{i}T000000000000Z-site" for i in range(1, 8)]
    repo, out_root, _ = make_environment(tmp_path, monkeypatch, build_ids)
    write_deployment_report(repo, "01-old", "remote-production", build_ids[0])
    write_deployment_report(repo, "02-new", "remote-staging", build_ids[6])

    result = prune_outputs(repo, keep=5)

    assert result["status"] == "passed"
    assert build_ids[0] in result["protected_builds"]
    assert (out_root / "builds" / "staging" / build_ids[0]).is_dir()
    assert result["moved_builds"] == [build_ids[1]]


def test_prune_uses_latest_deployment_per_target(tmp_path, monkeypatch):
    build_ids = [f"2026070{i}T000000000000Z-site" for i in range(1, 8)]
    repo, out_root, _ = make_environment(tmp_path, monkeypatch, build_ids)
    write_deployment_report(repo, "01-old", "remote-staging", build_ids[0])
    write_deployment_report(repo, "02-superseding", "remote-staging", build_ids[6])

    result = prune_outputs(repo, keep=5)

    assert build_ids[0] in result["moved_builds"]
    assert not (out_root / "builds" / "staging" / build_ids[0]).exists()


def test_prune_refuses_when_history_marker_missing(tmp_path, monkeypatch):
    build_ids = [f"2026070{i}T000000000000Z-site" for i in range(1, 8)]
    repo, out_root, history = make_environment(tmp_path, monkeypatch, build_ids)
    (history / ".mrp-history-root").unlink()

    result = prune_outputs(repo, keep=1)

    assert result["status"] == "failed"
    assert result["stage"] == "safety"
    assert result["moved_builds"] == []
    for build_id in build_ids:
        assert (out_root / "builds" / "staging" / build_id).is_dir()


def test_prune_dry_run_moves_nothing(tmp_path, monkeypatch):
    build_ids = [f"2026070{i}T000000000000Z-site" for i in range(1, 8)]
    repo, out_root, history = make_environment(tmp_path, monkeypatch, build_ids)

    result = prune_outputs(repo, keep=5, dry_run=True)

    assert result["status"] == "passed"
    assert result["moved_builds"] == build_ids[:2]
    for build_id in build_ids:
        assert (out_root / "builds" / "staging" / build_id).is_dir()
    assert not (history / "builds").exists()


def test_prune_skips_collisions_without_deleting_source(tmp_path, monkeypatch):
    build_ids = [f"2026070{i}T000000000000Z-site" for i in range(1, 8)]
    repo, out_root, history = make_environment(tmp_path, monkeypatch, build_ids)
    collision = history / "builds" / "staging" / build_ids[0]
    collision.mkdir(parents=True)

    result = prune_outputs(repo, keep=5)

    assert result["status"] == "failed"
    assert build_ids[0] not in result["moved_builds"]
    assert (out_root / "builds" / "staging" / build_ids[0]).is_dir()
    assert result["errors"][0]["field"] == build_ids[0]
    assert build_ids[1] in result["moved_builds"]


def test_prune_moves_orphaned_cache_workspaces(tmp_path, monkeypatch):
    build_ids = [f"2026070{i}T000000000000Z-site" for i in range(1, 4)]
    repo, out_root, history = make_environment(
        tmp_path, monkeypatch, build_ids, cache_ids=build_ids + ["20260601T000000000000Z-failed"]
    )

    result = prune_outputs(repo, keep=5)

    assert result["status"] == "passed"
    assert result["moved_builds"] == []
    assert result["moved_caches"] == ["20260601T000000000000Z-failed"]
    assert (history / "cache" / "20260601T000000000000Z-failed").is_dir()


def test_prune_moves_old_production_archives(tmp_path, monkeypatch):
    build_ids = [f"2026070{i}T000000000000Z-site" for i in range(1, 4)]
    repo, out_root, history = make_environment(tmp_path, monkeypatch, build_ids)
    archive_ids = [f"production-2026070{i}T000000Z" for i in range(1, 8)]
    for archive_id in archive_ids:
        archive_dir = out_root / "archive" / archive_id
        archive_dir.mkdir(parents=True)
        (archive_dir / "index.html").write_text("<html></html>\n")

    result = prune_outputs(repo, keep=5)

    assert result["status"] == "passed"
    assert result["moved_archives"] == archive_ids[:2]
    assert result["kept_archives"] == archive_ids[2:]
    for archive_id in archive_ids[:2]:
        assert not (out_root / "archive" / archive_id).exists()
        assert (history / "archive" / archive_id / "index.html").is_file()
    for archive_id in archive_ids[2:]:
        assert (out_root / "archive" / archive_id).is_dir()


def test_prune_ignores_non_archive_directories_in_archive_root(tmp_path, monkeypatch):
    build_ids = ["20260701T000000000000Z-site"]
    repo, out_root, _ = make_environment(tmp_path, monkeypatch, build_ids)
    stray = out_root / "archive" / "manual-backup"
    stray.mkdir(parents=True)

    result = prune_outputs(repo, keep=1)

    assert result["status"] == "passed"
    assert result["moved_archives"] == []
    assert stray.is_dir()


def test_prune_protects_builds_deployed_from_another_clone(tmp_path, monkeypatch):
    build_ids = [f"2026070{i}T000000000000Z-site" for i in range(1, 8)]
    repo, out_root, _ = make_environment(tmp_path, monkeypatch, build_ids)
    prod = out_root / "prod"
    prod.mkdir()
    (prod / "build-manifest.json").write_text(json.dumps({"build_id": build_ids[0]}))

    result = prune_outputs(repo, keep=5)

    assert result["status"] == "passed"
    assert build_ids[0] in result["protected_builds"]
    assert (out_root / "builds" / "staging" / build_ids[0]).is_dir()
    assert result["moved_builds"] == [build_ids[1]]


def test_prune_ignores_corrupt_target_manifest(tmp_path, monkeypatch):
    build_ids = [f"2026070{i}T000000000000Z-site" for i in range(1, 8)]
    repo, out_root, _ = make_environment(tmp_path, monkeypatch, build_ids)
    prod = out_root / "prod"
    prod.mkdir()
    (prod / "build-manifest.json").write_text("not json")

    result = prune_outputs(repo, keep=5)

    assert result["status"] == "passed"
    assert result["moved_builds"] == build_ids[:2]


def test_prune_skips_when_another_prune_holds_the_lock(tmp_path, monkeypatch):
    build_ids = [f"2026070{i}T000000000000Z-site" for i in range(1, 8)]
    repo, out_root, history = make_environment(tmp_path, monkeypatch, build_ids)
    with open(out_root / ".prune.lock", "w") as competing:
        fcntl.flock(competing, fcntl.LOCK_EX | fcntl.LOCK_NB)

        result = prune_outputs(repo, keep=5)

    assert result["status"] == "skipped"
    assert result["stage"] == "lock"
    assert result["moved_builds"] == []
    for build_id in build_ids:
        assert (out_root / "builds" / "staging" / build_id).is_dir()
    assert not (history / "builds").exists()


def test_prune_releases_lock_for_subsequent_runs(tmp_path, monkeypatch):
    build_ids = [f"2026070{i}T000000000000Z-site" for i in range(1, 8)]
    repo, _, _ = make_environment(tmp_path, monkeypatch, build_ids)

    first = prune_outputs(repo, keep=5)
    second = prune_outputs(repo, keep=5)

    assert first["status"] == "passed"
    assert second["status"] == "passed"
    assert second["moved_builds"] == []


def test_prune_rejects_keep_below_one(tmp_path, monkeypatch):
    build_ids = ["20260701T000000000000Z-site"]
    repo, _, _ = make_environment(tmp_path, monkeypatch, build_ids)

    result = prune_outputs(repo, keep=0)

    assert result["status"] == "failed"
    assert result["stage"] == "config"
