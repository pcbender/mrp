from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import yaml
from jsonschema import Draft202012Validator, FormatChecker


CONTENT_EXTENSIONS = {".yaml", ".yml", ".json"}
PUBLISHABLE_STATUSES = {"staged", "verified", "approved", "live"}
SCHEMA_NAMES = {
    "site": "site.schema.json",
    "artist": "artist.schema.json",
    "release": "release.schema.json",
    "assets": "asset-manifest.schema.json",
    "page": "page.schema.json",
    "post": "post.schema.json",
    "redirects": "redirects.schema.json",
    "clone_record": "clone-record.schema.json",
    "clone_assets": "clone-asset-manifest.schema.json",
}


def validate_repository(repo: str | Path, release: str | None = None) -> dict[str, Any]:
    root = Path(repo).resolve()
    schema_dir = Path(__file__).resolve().parents[1] / "schemas"
    errors: list[dict[str, str]] = []
    warnings: list[dict[str, str]] = []

    site_path = root / "content" / "site.yaml"
    if site_path.exists():
        site = load_content(site_path, errors)
        if site is not None:
            errors.extend(validate_schema(site_path, site, schema_dir / SCHEMA_NAMES["site"]))
    else:
        errors.append(error_record(site_path, "$", "Missing content/site.yaml."))

    artists = load_records(root / "content" / "artists", "artist", schema_dir, errors)
    releases = load_records(root / "content" / "releases", "release", schema_dir, errors)
    pages = load_records(root / "content" / "pages", "page", schema_dir, errors)
    posts = load_records(root / "content" / "posts", "post", schema_dir, errors)
    clone_pages = load_records(root / "content" / "clone" / "pages", "clone_record", schema_dir, errors)
    clone_posts = load_records(root / "content" / "clone" / "posts", "clone_record", schema_dir, errors)
    if release:
        releases = [item for item in releases if item["data"].get("release", {}).get("id") == release]
        if not releases:
            errors.append(error_record(root / "content" / "releases", "release", f"Unknown release: {release}"))

    asset_manifest_path = root / "content" / "assets" / "manifest.yaml"
    asset_manifest = None
    if asset_manifest_path.exists():
        asset_manifest = load_content(asset_manifest_path, errors)
        if asset_manifest is not None:
            errors.extend(
                validate_schema(asset_manifest_path, asset_manifest, schema_dir / SCHEMA_NAMES["assets"])
            )

    clone_asset_manifest_path = root / "content" / "clone" / "assets" / "manifest.yaml"
    clone_asset_manifest = None
    if clone_asset_manifest_path.exists():
        clone_asset_manifest = load_content(clone_asset_manifest_path, errors)
        if clone_asset_manifest is not None:
            errors.extend(
                validate_schema(
                    clone_asset_manifest_path,
                    clone_asset_manifest,
                    schema_dir / SCHEMA_NAMES["clone_assets"],
                )
            )

    redirects_path = root / "content" / "redirects.yaml"
    if redirects_path.exists():
        redirects = load_content(redirects_path, errors)
        if redirects is not None:
            errors.extend(validate_schema(redirects_path, redirects, schema_dir / SCHEMA_NAMES["redirects"]))

    errors.extend(validate_duplicates(artists, "artist", "id"))
    errors.extend(validate_duplicates(releases, "release", "id"))
    errors.extend(validate_duplicates(releases, "release", "slug"))
    errors.extend(validate_duplicates(pages, "page", "id"))
    errors.extend(validate_duplicates(pages, "page", "slug"))
    errors.extend(validate_duplicates(posts, "post", "id"))
    errors.extend(validate_duplicates(posts, "post", "slug"))
    errors.extend(validate_duplicates(clone_pages + clone_posts, "clone", "id"))
    errors.extend(validate_artist_references(releases, artists))
    errors.extend(validate_member_slugs(artists))
    for record in releases:
        errors.extend(validate_release_stem_ids(record["path"], record["data"]))
    errors.extend(validate_member_and_feature_references(releases, artists))
    errors.extend(validate_asset_manifest(root, asset_manifest_path, asset_manifest))
    errors.extend(validate_release_assets(root, releases))

    status = "passed" if not errors else "failed"
    result = {
        "command": "validate",
        "status": status,
        "repo": str(root),
        "release": release,
        "generated_at": datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
        "summary": {
            "errors": len(errors),
            "warnings": len(warnings),
            "artists": len(artists),
            "releases": len(releases),
            "pages": len(pages),
            "posts": len(posts),
            "clone_pages": len(clone_pages),
            "clone_posts": len(clone_posts),
            "clone_assets": len((clone_asset_manifest or {}).get("clone_assets", [])),
        },
        "errors": errors,
        "warnings": warnings,
    }
    result["report_path"] = report_path(root, result["generated_at"])
    write_report(root, result)
    return result


def load_records(
    directory: Path,
    kind: str,
    schema_dir: Path,
    errors: list[dict[str, str]],
) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    if not directory.is_dir():
        return records

    for path in sorted(directory.iterdir()):
        if not path.is_file() or path.suffix not in CONTENT_EXTENSIONS:
            continue
        data = load_content(path, errors)
        if data is None:
            continue
        errors.extend(validate_schema(path, data, schema_dir / SCHEMA_NAMES[kind]))
        records.append({"path": path, "data": data})
    return records


def load_content(path: Path, errors: list[dict[str, str]]) -> Any | None:
    try:
        if path.suffix == ".json":
            return json.loads(path.read_text(encoding="utf-8"))
        return yaml.safe_load(path.read_text(encoding="utf-8"))
    except Exception as exc:  # noqa: BLE001 - converted to validation error.
        errors.append(error_record(path, "$", f"Could not parse content: {exc}"))
        return None


def load_schema(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def validate_schema(path: Path, data: Any, schema_path: Path) -> list[dict[str, str]]:
    validator = Draft202012Validator(load_schema(schema_path), format_checker=FormatChecker())
    return [
        error_record(path, ".".join(str(part) for part in error.absolute_path) or "$", error.message)
        for error in sorted(validator.iter_errors(data), key=lambda item: list(item.absolute_path))
    ]


def validate_duplicates(records: list[dict[str, Any]], root_key: str, field: str) -> list[dict[str, str]]:
    seen: dict[str, Path] = {}
    errors: list[dict[str, str]] = []
    for record in records:
        value = record["data"].get(root_key, {}).get(field)
        if not value:
            continue
        if value in seen:
            errors.append(
                error_record(
                    record["path"],
                    f"{root_key}.{field}",
                    f"Duplicate {root_key} {field}: {value} also appears in {seen[value]}",
                )
            )
        else:
            seen[value] = record["path"]
    return errors


def validate_artist_references(
    releases: list[dict[str, Any]],
    artists: list[dict[str, Any]],
) -> list[dict[str, str]]:
    artist_ids = {record["data"].get("artist", {}).get("id") for record in artists}
    errors: list[dict[str, str]] = []
    for record in releases:
        artist_id = record["data"].get("release", {}).get("artist_id")
        if artist_id and artist_id not in artist_ids:
            errors.append(
                error_record(
                    record["path"],
                    "release.artist_id",
                    f"Release references missing artist_id: {artist_id}",
                )
            )
    return errors


def validate_member_slugs(artists: list[dict[str, Any]]) -> list[dict[str, str]]:
    """Member slugs must be unique within one artist's members list."""
    errors: list[dict[str, str]] = []
    for record in artists:
        seen: set[str] = set()
        members = record["data"].get("artist", {}).get("members") or []
        for index, member in enumerate(members):
            slug = member.get("slug")
            if not slug:
                continue
            if slug in seen:
                errors.append(
                    error_record(
                        record["path"],
                        f"artist.members.{index}.slug",
                        f"Duplicate member slug within artist: {slug}",
                    )
                )
            seen.add(slug)
    return errors


def _release_songs(release: dict[str, Any]) -> list[tuple[str, dict[str, Any]]]:
    """Yield (field_prefix, song) for a release's single song and/or track list."""
    songs: list[tuple[str, dict[str, Any]]] = []
    song = release.get("song")
    if isinstance(song, dict):
        songs.append(("release.song", song))
    tracks = release.get("tracks")
    if isinstance(tracks, list):
        for index, track in enumerate(tracks):
            if isinstance(track, dict):
                songs.append((f"release.tracks.{index}", track))
    return songs


def validate_release_stem_ids(path: Path, data: dict[str, Any]) -> list[dict[str, str]]:
    """Stem ids must be unique within each song/track.

    JSON Schema can reject duplicate stem records, but it cannot express
    uniqueness for one property across otherwise distinct objects. Keep this
    repository-level check alongside the other cross-record invariants.
    """
    release = data.get("release", {})
    errors: list[dict[str, str]] = []
    for prefix, song in _release_songs(release):
        seen: set[str] = set()
        for index, stem in enumerate(song.get("stems") or []):
            if not isinstance(stem, dict):
                continue
            stem_id = stem.get("id")
            if not stem_id:
                continue
            if stem_id in seen:
                errors.append(
                    error_record(
                        path,
                        f"{prefix}.stems.{index}.id",
                        f"Duplicate stem id within track: {stem_id}",
                    )
                )
            seen.add(stem_id)
    return errors


def validate_member_and_feature_references(
    releases: list[dict[str, Any]],
    artists: list[dict[str, Any]],
) -> list[dict[str, str]]:
    """Resolve structured attribution references across files.

    - featuring ids (release- and track-level) and performers[].artist must
      match an existing artist record.
    - performers[].member must match a member slug on the release's owning
      artist (release.artist_id).
    """
    artist_ids = {record["data"].get("artist", {}).get("id") for record in artists}
    members_by_artist: dict[str, set[str]] = {}
    for record in artists:
        artist = record["data"].get("artist", {})
        slugs = {m.get("slug") for m in (artist.get("members") or []) if m.get("slug")}
        members_by_artist[artist.get("id")] = slugs

    errors: list[dict[str, str]] = []
    for record in releases:
        release = record["data"].get("release", {})
        path = record["path"]
        owning_artist_id = release.get("artist_id")

        for index, feat in enumerate(release.get("featuring") or []):
            if feat not in artist_ids:
                errors.append(
                    error_record(
                        path,
                        f"release.featuring.{index}",
                        f"featuring references missing artist: {feat}",
                    )
                )

        for prefix, song in _release_songs(release):
            for index, feat in enumerate(song.get("featuring") or []):
                if feat not in artist_ids:
                    errors.append(
                        error_record(
                            path,
                            f"{prefix}.featuring.{index}",
                            f"featuring references missing artist: {feat}",
                        )
                    )
            for index, performer in enumerate(song.get("performers") or []):
                artist_ref = performer.get("artist")
                if artist_ref is not None and artist_ref not in artist_ids:
                    errors.append(
                        error_record(
                            path,
                            f"{prefix}.performers.{index}.artist",
                            f"performer references missing artist: {artist_ref}",
                        )
                    )
                member_ref = performer.get("member")
                if member_ref is not None and member_ref not in members_by_artist.get(
                    owning_artist_id, set()
                ):
                    errors.append(
                        error_record(
                            path,
                            f"{prefix}.performers.{index}.member",
                            f"performer references unknown member '{member_ref}' "
                            f"for artist {owning_artist_id}",
                        )
                    )
    return errors


def validate_asset_manifest(root: Path, path: Path, manifest: Any | None) -> list[dict[str, str]]:
    if not manifest:
        return []
    errors: list[dict[str, str]] = []
    for index, asset in enumerate(manifest.get("assets", [])):
        if asset.get("required") and not (root / asset.get("path", "")).is_file():
            errors.append(
                error_record(
                    path,
                    f"assets.{index}.path",
                    f"Required asset file is missing: {asset.get('path')}",
                )
            )
    return errors


def validate_release_assets(root: Path, releases: list[dict[str, Any]]) -> list[dict[str, str]]:
    errors: list[dict[str, str]] = []
    for record in releases:
        release = record["data"].get("release", {})
        if release.get("status") not in PUBLISHABLE_STATUSES:
            continue
        cover = release.get("cover_image")
        if cover and not (root / cover).is_file():
            errors.append(
                error_record(record["path"], "release.cover_image", f"Missing cover image: {cover}")
            )
    return errors


def report_path(root: Path, generated_at: str) -> str:
    timestamp = generated_at.replace("-", "").replace(":", "").replace("Z", "Z")
    path = root / "reports" / "validation" / f"{timestamp}.json"
    return path.relative_to(root).as_posix()


def write_report(root: Path, result: dict[str, Any]) -> None:
    path = root / result["report_path"]
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n")


def error_record(path: Path, field: str, message: str, severity: str = "error") -> dict[str, str]:
    return {
        "file_path": str(path),
        "field": field,
        "severity": severity,
        "message": message,
    }


def format_validation(result: dict[str, Any]) -> str:
    summary = result["summary"]
    lines = [
        f"Validation {result['status']}",
        f"Errors: {summary['errors']}",
        f"Warnings: {summary['warnings']}",
        f"Report: {result['report_path']}",
    ]
    for error in result["errors"]:
        lines.append(f"- {error['file_path']} {error['field']}: {error['message']}")
    return "\n".join(lines)
