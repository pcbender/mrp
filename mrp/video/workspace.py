from __future__ import annotations

import hashlib
import json
import os
import re
from collections import defaultdict
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from collections.abc import Callable
from typing import Any

import librosa
import numpy as np
import soundfile as sf
import yaml
from PIL import Image, ImageDraw, ImageFont
from pydantic import ValidationError

from mrp.video.alignment import SpirophonicAlignmentError, align_project
from mrp.video.analysis import SpirophonicAnalysisError, analyze_project
from mrp.video.cards import SpirophonicCardError
from mrp.video.encoder import SpirophonicEncodingError
from mrp.video.pipeline import (
    SpirophonicPipelineError,
    plan_project_video,
    render_project_video,
)
from mrp.video.project import (
    LYRIC_LESS_SECTION_TYPES,
    AlignmentConfig,
    AnalysisConfig,
    AudioConfig,
    CardConfig,
    CardsConfig,
    LyricsConfig,
    ProjectManifest,
    SpirophonicValidationError,
    StructuredLyrics,
    TextConfig,
    load_structured_lyrics,
    validate_project,
)
from mrp.video.render_manifest import SpirophonicManifestError
from mrp.video.renderer import (
    SpirophonicRendererError,
    load_render_context,
    render_dimensions,
    render_frame,
    render_frame_file,
)
from mrp.video.verification import SpirophonicVerificationError
from mrp.video.track_project import (
    ADAPTER_VERSION,
    TrackProjectDocument,
    TrackSource,
)

SEMANTIC_ROLES = ("drums", "bass", "vocals", "instruments")
_SLUG_PATTERN = re.compile(r"^[a-z0-9][a-z0-9-]*$")
_RENDER_ID_PATTERN = re.compile(r"^[a-zA-Z0-9][a-zA-Z0-9_-]{0,63}$")
_SECTION_PATTERN = re.compile(r"^\[(?P<label>[^]]+)]$")


class MRPVideoAdapterError(Exception):
    def __init__(self, *problems: str):
        self.problems = tuple(problems)
        super().__init__("; ".join(problems))


@dataclass(frozen=True, slots=True)
class TrackWorkspace:
    repo: Path
    track_key: str
    source_dir: Path
    project_path: Path
    aligned_path: Path
    processed_dir: Path
    analysis_dir: Path
    previews_dir: Path
    renders_dir: Path
    logs_dir: Path
    runtime_manifest_path: Path
    runtime_lyrics_path: Path
    preflight_path: Path
    artifact_index_path: Path

    @classmethod
    def for_track(cls, repo: Path, track_key: str) -> "TrackWorkspace":
        source_dir = repo / "assets" / "source" / "video" / track_key
        processed_dir = repo / "assets" / "processed" / "video" / track_key
        analysis_dir = processed_dir / "analysis"
        logs_dir = processed_dir / "logs"
        return cls(
            repo=repo,
            track_key=track_key,
            source_dir=source_dir,
            project_path=source_dir / "project.yaml",
            aligned_path=source_dir / "lyrics.aligned.yaml",
            processed_dir=processed_dir,
            analysis_dir=analysis_dir,
            previews_dir=processed_dir / "previews",
            renders_dir=processed_dir / "renders",
            logs_dir=logs_dir,
            runtime_manifest_path=analysis_dir / "project.runtime.yaml",
            runtime_lyrics_path=analysis_dir / "lyrics.yaml",
            preflight_path=logs_dir / "preflight.json",
            artifact_index_path=logs_dir / "artifacts.json",
        )

    def ensure_generated_dirs(self) -> None:
        for path in (
            self.analysis_dir,
            self.previews_dir,
            self.renders_dir,
            self.logs_dir,
        ):
            path.mkdir(parents=True, exist_ok=True)

    def relative(self, path: Path) -> str:
        return path.resolve().relative_to(self.repo).as_posix()


@dataclass(frozen=True, slots=True)
class StemSource:
    id: str
    role: str
    path: Path
    source_role: str


@dataclass(frozen=True, slots=True)
class PreparedTrack:
    release_slug: str
    track_slug: str
    track_title: str
    track_key: str
    workspace: TrackWorkspace
    runtime_manifest_path: Path
    project_hash: str
    input_hashes: dict[str, str]
    input_fingerprint: str
    aggregation: dict[str, tuple[str, ...]]
    stale_artifacts: tuple[dict[str, Any], ...]
    master_duration: float
    stem_durations: dict[str, float]
    lyric_directions: tuple[str, ...] = ()

    def summary(self) -> dict[str, Any]:
        return {
            "status": "passed",
            "release": self.release_slug,
            "track": self.track_slug,
            "title": self.track_title,
            "track_key": self.track_key,
            "project": self.workspace.relative(self.workspace.project_path),
            "aligned_lyrics": self.workspace.relative(self.workspace.aligned_path),
            "runtime_manifest": self.workspace.relative(self.runtime_manifest_path),
            "processed_root": self.workspace.relative(self.workspace.processed_dir),
            "project_hash": self.project_hash,
            "input_fingerprint": self.input_fingerprint,
            "input_hashes": dict(sorted(self.input_hashes.items())),
            "aggregation": {
                role: list(ids) for role, ids in sorted(self.aggregation.items())
            },
            "stale_artifacts": list(self.stale_artifacts),
            "master_duration": self.master_duration,
            "stem_durations": dict(sorted(self.stem_durations.items())),
            "lyric_directions": list(self.lyric_directions),
        }


@dataclass(frozen=True, slots=True)
class _TrackSelection:
    repo: Path
    release_path: Path
    document: dict[str, Any]
    release: dict[str, Any]
    track: dict[str, Any]
    release_slug: str
    track_slug: str
    track_key: str


def _read_yaml_mapping(path: Path) -> dict[str, Any]:
    try:
        value = yaml.safe_load(path.read_text(encoding="utf-8"))
    except OSError as exc:
        raise MRPVideoAdapterError(f"cannot read {path}: {exc}") from exc
    except yaml.YAMLError as exc:
        raise MRPVideoAdapterError(f"malformed YAML in {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise MRPVideoAdapterError(f"{path} must contain a YAML mapping")
    return value


def _atomic_write_text(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    try:
        temporary.write_text(content, encoding="utf-8")
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def _write_yaml(path: Path, value: dict[str, Any]) -> None:
    _atomic_write_text(
        path,
        yaml.safe_dump(value, sort_keys=False, allow_unicode=True),
    )


def _write_json(path: Path, value: dict[str, Any]) -> None:
    _atomic_write_text(path, json.dumps(value, indent=2, sort_keys=True) + "\n")


def _select_track(repo: Path, release_slug: str, track_slug: str | None) -> _TrackSelection:
    root = repo.expanduser().resolve()
    if not _SLUG_PATTERN.fullmatch(release_slug):
        raise MRPVideoAdapterError(f"invalid release slug: {release_slug}")
    release_path = root / "content" / "releases" / f"{release_slug}.yaml"
    if not release_path.is_file():
        raise MRPVideoAdapterError(f"release does not exist: {release_path}")
    document = _read_yaml_mapping(release_path)
    release = document.get("release")
    if not isinstance(release, dict):
        raise MRPVideoAdapterError(f"{release_path}: release must be a mapping")

    model = release.get("model")
    if model == "song":
        track = release.get("song")
        if not isinstance(track, dict):
            raise MRPVideoAdapterError(f"{release_path}: song must be a mapping")
        selected_slug = str(track.get("slug") or "")
        if track_slug is not None and track_slug != selected_slug:
            raise MRPVideoAdapterError(
                f"single release track is {selected_slug}, not {track_slug}"
            )
    elif model == "album":
        if not track_slug:
            raise MRPVideoAdapterError("--track is required for an EP or album")
        tracks = release.get("tracks")
        if not isinstance(tracks, list):
            raise MRPVideoAdapterError(f"{release_path}: tracks must be a list")
        matches = [item for item in tracks if isinstance(item, dict) and item.get("slug") == track_slug]
        if len(matches) != 1:
            raise MRPVideoAdapterError(
                f"release {release_slug} has no unique track named {track_slug}"
            )
        track = matches[0]
        selected_slug = track_slug
    else:
        raise MRPVideoAdapterError(f"unsupported release model: {model}")

    artist_id = str(release.get("artist_id") or "")
    if not _SLUG_PATTERN.fullmatch(artist_id) or not _SLUG_PATTERN.fullmatch(selected_slug):
        raise MRPVideoAdapterError("artist and track identifiers must be slug-like")
    track_key = f"{artist_id}--{selected_slug}"
    return _TrackSelection(
        repo=root,
        release_path=release_path,
        document=document,
        release=release,
        track=track,
        release_slug=release_slug,
        track_slug=selected_slug,
        track_key=track_key,
    )


def _resolve_input(repo: Path, value: str | Path, label: str) -> Path:
    source = Path(value).expanduser()
    resolved = source.resolve() if source.is_absolute() else (repo / source).resolve()
    if not resolved.is_file():
        raise MRPVideoAdapterError(f"{label} does not exist or is not a file: {resolved}")
    return resolved


def _semantic_role(role: str) -> str:
    if role == "other":
        return "instruments"
    if role not in SEMANTIC_ROLES:
        raise MRPVideoAdapterError(f"unsupported stem role: {role}")
    return role


def _stem_groups(selection: _TrackSelection) -> dict[str, list[StemSource]]:
    groups: dict[str, list[StemSource]] = defaultdict(list)
    seen: set[str] = set()
    stems = selection.track.get("stems") or []
    if not isinstance(stems, list):
        raise MRPVideoAdapterError("track stems must be a list")
    for raw in stems:
        if not isinstance(raw, dict):
            raise MRPVideoAdapterError("each stem must be a mapping")
        stem_id = str(raw.get("id") or "")
        if stem_id in seen:
            raise MRPVideoAdapterError(f"duplicate stem id: {stem_id}")
        seen.add(stem_id)
        if raw.get("enabled", True) is False:
            continue
        role = str(raw.get("role") or "")
        path_value = raw.get("path")
        if not stem_id or not path_value:
            raise MRPVideoAdapterError("enabled stems require id, role, and path")
        semantic_role = _semantic_role(role)
        groups[semantic_role].append(
            StemSource(
                id=stem_id,
                role=semantic_role,
                source_role=role,
                path=_resolve_input(
                    selection.repo,
                    str(path_value),
                    f"stem {stem_id}",
                ),
            )
        )
    return {
        role: sorted(sources, key=lambda source: source.id)
        for role, sources in sorted(groups.items())
    }


def _project_placeholders(groups: dict[str, list[StemSource]]) -> AudioConfig:
    return AudioConfig(
        master=Path("@mrp/master"),
        stems={role: Path(f"@mrp/stems/{role}") for role in groups},
    )


def _default_project(
    selection: _TrackSelection,
    groups: dict[str, list[StemSource]],
) -> ProjectManifest:
    language = str(selection.release.get("language") or "en")
    return ProjectManifest(
        version=1,
        title=str(selection.track.get("title") or selection.track_slug),
        audio=_project_placeholders(groups),
        lyrics=LyricsConfig(
            source=Path("@mrp/lyrics"),
            aligned=Path("lyrics.aligned.yaml"),
            language=language,
        ),
        cards=CardsConfig(
            opening=CardConfig(
                file=Path("@mrp/cover"), duration=3, fade=0.5
            ),
            closing=CardConfig(
                file=Path("@mrp/cover"), duration=4, fade=0.75
            ),
        ),
        text=TextConfig(font=Path("@mrp/font")),
        analysis=AnalysisConfig(cache_dir=Path("cache/analysis")),
        alignment=AlignmentConfig(cache_dir=Path("cache/alignment")),
    )


def _load_source_project(path: Path) -> TrackProjectDocument:
    value = _read_yaml_mapping(path)
    try:
        return TrackProjectDocument.model_validate(value)
    except ValidationError as exc:
        problems = []
        for error in exc.errors(include_url=False):
            location = ".".join(str(part) for part in error["loc"])
            problems.append(f"{path}: {location}: {error['msg']}")
        raise MRPVideoAdapterError(*problems) from exc


def _branding_actors(root: Path, artist_id: str) -> dict[str, Any]:
    """Snapshot the label + artist branding actors from the library, pinned.

    Returns ``{actor_id: ActorConfig}`` for whichever of ``maricopa-records``
    and ``artist-{artist_id}`` exist in the library — missing actors are
    silently skipped so prepare never fails on branding. Each snapshot pins its
    library revision (mirroring the admin's actor_import), so the casting
    editor shows it as a current library import.
    """
    from mrp.video.actor_library import actor_revision, load_library_actor
    from mrp.video.project import ActorConfig

    branding: dict[str, Any] = {}
    for actor_id in ("maricopa-records", f"artist-{artist_id}"):
        actor = load_library_actor(root, actor_id)
        if actor is None:
            continue
        payload = actor.model_dump(mode="json", exclude_none=True)
        payload["character"] = actor.components[0].role
        payload["library_source"] = {
            "actor_id": actor_id,
            "revision": actor_revision(actor),
        }
        branding[actor_id] = ActorConfig.model_validate(payload)
    return branding


def _source_project(
    selection: _TrackSelection,
    groups: dict[str, list[StemSource]],
    workspace: TrackWorkspace,
    *,
    force: bool,
) -> TrackProjectDocument:
    release_relative = selection.release_path.relative_to(selection.repo)
    source = TrackSource(
        release=release_relative,
        track_slug=selection.track_slug,
        track_key=selection.track_key,
        artist_id=str(selection.release["artist_id"]),
    )
    if workspace.project_path.is_file() and not force:
        existing = _load_source_project(workspace.project_path)
        if existing.source.track_key != selection.track_key:
            raise MRPVideoAdapterError(
                f"project belongs to {existing.source.track_key}, not {selection.track_key}"
            )
        project_value = existing.project.model_dump(mode="json", exclude_none=True)
        project_value["title"] = str(
            selection.track.get("title") or selection.track_slug
        )
        project_value["audio"] = _project_placeholders(groups).model_dump(
            mode="json", exclude_none=True
        )
        project_value["lyrics"]["source"] = "@mrp/lyrics"
        project_value["lyrics"]["aligned"] = "lyrics.aligned.yaml"
        project_value["cards"]["opening"]["file"] = "@mrp/cover"
        project_value["cards"]["closing"]["file"] = "@mrp/cover"
        project_value["text"]["font"] = "@mrp/font"
        project = ProjectManifest.model_validate(project_value)
    else:
        # Fresh project (or force-rebuild): seed the roster with the branding
        # actors so a track arrives with its label + artist marks pre-cast.
        # Only here, never on re-normalize, so a later deletion sticks.
        project = _default_project(selection, groups)
        branding = _branding_actors(selection.repo, source.artist_id)
        if branding:
            project.visuals.actors.update(branding)
    document = TrackProjectDocument(source=source, project=project)
    _write_yaml(
        workspace.project_path,
        document.model_dump(mode="json", exclude_none=True),
    )
    return document


def _link_release_project(
    selection: _TrackSelection,
    workspace: TrackWorkspace,
    *,
    update_release: bool,
) -> None:
    project_relative = workspace.project_path.relative_to(selection.repo).as_posix()
    current = selection.track.get("music_video")
    if current is not None and not isinstance(current, dict):
        raise MRPVideoAdapterError("track music_video must be a mapping")
    if isinstance(current, dict):
        declared = current.get("project")
        if declared and declared != project_relative:
            raise MRPVideoAdapterError(
                f"music_video.project is {declared}, expected {project_relative}"
            )
    if not update_release:
        return
    video = dict(current or {})
    video["project"] = project_relative
    video.setdefault("status", "draft")
    selection.track["music_video"] = video
    _write_yaml(selection.release_path, selection.document)


# Suno and ACE Studio put song structure and performance directions in the same
# [brackets]: "[Verse 1]" names a section, "[breathy male vocals]" is a note to
# the generator that is never sung. Only a known structure name opens a section.
_STRUCTURE_LABELS = frozenset(
    {
        "intro",
        "verse",
        "chorus",
        "pre-chorus",
        "post-chorus",
        "bridge",
        "outro",
        "refrain",
        "hook",
        "interlude",
        "breakdown",
        "instrumental",
        "solo",
        "guitar solo",
        "coda",
        "vamp",
        "tag",
        "ad-lib",
    }
)
_STRUCTURE_ALIASES = {
    "pre chorus": "pre-chorus",
    "prechorus": "pre-chorus",
    "post chorus": "post-chorus",
    "postchorus": "post-chorus",
    "ad lib": "ad-lib",
    "adlib": "ad-lib",
    "ad libs": "ad-lib",
    "ad-libs": "ad-lib",
    "adlibs": "ad-lib",
}


def _structure_label(label: str, extra: frozenset[str] = frozenset()) -> str | None:
    """The bracketed label if it names song structure, else None for a direction.

    Trailing numbers are ignored when matching, so "[Verse 1]" and "[Verse 2]"
    both read as a verse while keeping their distinct ids. A label containing
    "|" is always treated as structure — the explicit escape hatch for a name
    this vocabulary does not know.
    """
    if "|" in label:
        return label
    value = re.sub(r"\s+", " ", label).strip().casefold()
    value = re.sub(r"\s*\d+$", "", value).strip()
    canonical = _STRUCTURE_ALIASES.get(value, value)
    if canonical in _STRUCTURE_LABELS or canonical in extra:
        return label
    return None


def _section_type(label: str) -> str:
    value = label.split("|", 1)[0].strip().casefold()
    value = re.sub(r"\s+\d+$", "", value)
    aliases = {
        "pre chorus": "pre-chorus",
        "prechorus": "pre-chorus",
        "post chorus": "post-chorus",
        "postchorus": "post-chorus",
        "guitar solo": "instrumental",
        "solo": "instrumental",
    }
    return aliases.get(value, value.replace(" ", "-")) or "section"


def _slugify(value: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", value.casefold()).strip("-")
    return slug or "section"


def _lyrics_from_text(
    text: str,
    *,
    instrumental: bool,
    extra_labels: frozenset[str] = frozenset(),
) -> tuple[StructuredLyrics, tuple[str, ...]]:
    """Structure a pasted lyric, returning it with the directions it discarded.

    Performance directions are reported rather than dropped in silence: they
    vanish from the lyric the video and the published page use, and a lyric
    losing lines without saying so is the failure mode worth shouting about.
    """
    sections: list[dict[str, Any]] = []
    current: dict[str, Any] | None = None
    counts: dict[str, int] = defaultdict(int)
    directions: list[str] = []

    def start_section(label: str, section_type: str) -> dict[str, Any]:
        base = _slugify(label.split("|", 1)[0])
        counts[base] += 1
        section_id = base if counts[base] == 1 else f"{base}-{counts[base]}"
        return {
            "id": section_id,
            "type": section_type,
            "label": label.strip(),
            "lines": [],
        }

    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        match = _SECTION_PATTERN.fullmatch(line)
        if match:
            label = _structure_label(match.group("label").strip(), extra_labels)
            if label is None:
                directions.append(line)
                continue
            if current is not None:
                sections.append(current)
            current = start_section(label, _section_type(label))
            continue
        if current is None:
            current = start_section("Instrumental" if instrumental else "Verse", "instrumental" if instrumental else "verse")
        current["lines"].append({"text": line})
    if current is not None:
        sections.append(current)
    sections = [
        section
        for section in sections
        if section["lines"] or section["type"] in LYRIC_LESS_SECTION_TYPES
    ]
    if not sections:
        sections = [start_section("Instrumental", "instrumental")]
    try:
        structured = StructuredLyrics.model_validate(
            {"version": 1, "sections": sections}
        )
    except ValidationError as exc:
        raise MRPVideoAdapterError(f"could not structure track lyrics: {exc}") from exc
    return structured, tuple(directions)


def _structured_lyrics(selection: _TrackSelection) -> tuple[StructuredLyrics, tuple[str, ...]]:
    source_value = selection.track.get("lyrics_source")
    if source_value:
        candidate = Path(str(source_value)).expanduser()
        candidate = candidate.resolve() if candidate.is_absolute() else (selection.repo / candidate).resolve()
        if candidate.is_file() and candidate.suffix.casefold() in {".yaml", ".yml"}:
            try:
                return load_structured_lyrics(candidate), ()
            except SpirophonicValidationError as exc:
                raise MRPVideoAdapterError(*exc.problems) from exc
    text = str(
        selection.track.get("lyrics_raw")
        or selection.track.get("lyrics_text")
        or ""
    )
    return _lyrics_from_text(
        text,
        instrumental=bool(selection.track.get("instrumental", False)),
        extra_labels=track_structure_labels(selection.track),
    )


def track_structure_labels(track: dict[str, Any]) -> frozenset[str]:
    """Extra bracketed labels this track treats as song structure.

    A one-off a shared vocabulary should not have to carry.
    """
    values = track.get("section_tags") or ()
    return frozenset(
        re.sub(r"\s+", " ", str(value)).strip().casefold()
        for value in values
        if str(value).strip()
    )


def _default_font(explicit: Path | None) -> Path:
    candidates = []
    if explicit is not None:
        candidates.append(explicit.expanduser())
    configured = os.environ.get("MRP_VIDEO_FONT")
    if configured:
        candidates.append(Path(configured).expanduser())
    candidates.extend(
        [
            Path("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"),
            Path("/usr/share/fonts/truetype/liberation2/LiberationSans-Regular.ttf"),
        ]
    )
    for candidate in candidates:
        resolved = candidate.resolve()
        if resolved.is_file():
            return resolved
    raise MRPVideoAdapterError(
        "no video font is available; pass --font or set MRP_VIDEO_FONT"
    )


def _hash_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _audio_duration(path: Path, label: str) -> float:
    try:
        info = sf.info(path)
    except (OSError, RuntimeError) as exc:
        raise MRPVideoAdapterError(f"cannot inspect {label}: {exc}") from exc
    if info.samplerate <= 0 or info.frames <= 0:
        raise MRPVideoAdapterError(f"{label} has no positive audio duration")
    return info.frames / info.samplerate


def _fingerprint(project_hash: str, input_hashes: dict[str, str]) -> str:
    payload = json.dumps(
        {
            "adapter_version": ADAPTER_VERSION,
            "project": project_hash,
            "inputs": dict(sorted(input_hashes.items())),
        },
        sort_keys=True,
        separators=(",", ":"),
    ).encode()
    return hashlib.sha256(payload).hexdigest()


def _aggregate_stems(
    workspace: TrackWorkspace,
    role: str,
    sources: list[StemSource],
    *,
    source_hashes: dict[str, str],
    master_path: Path,
) -> Path:
    if len(sources) == 1:
        return sources[0].path
    try:
        master_info = sf.info(master_path)
    except (OSError, RuntimeError) as exc:
        raise MRPVideoAdapterError(f"cannot inspect master audio: {exc}") from exc
    payload = json.dumps(
        {
            "version": 1,
            "method": "arithmetic-mean-mono",
            "role": role,
            "sample_rate": master_info.samplerate,
            "frames": master_info.frames,
            "members": [
                {"id": source.id, "sha256": source_hashes[source.id]}
                for source in sources
            ],
        },
        sort_keys=True,
        separators=(",", ":"),
    ).encode()
    aggregate_hash = hashlib.sha256(payload).hexdigest()
    output = workspace.analysis_dir / "stems" / f"{role}-{aggregate_hash[:20]}.wav"
    if output.is_file():
        return output
    accumulator = np.zeros(master_info.frames, dtype=np.float64)
    for source in sources:
        try:
            signal, _sample_rate = librosa.load(
                source.path,
                sr=master_info.samplerate,
                mono=True,
            )
        except Exception as exc:
            raise MRPVideoAdapterError(
                f"cannot decode stem {source.id}: {exc}"
            ) from exc
        fitted = np.zeros(master_info.frames, dtype=np.float64)
        length = min(len(signal), master_info.frames)
        fitted[:length] = signal[:length]
        accumulator += fitted
    aggregate = np.asarray(
        np.clip(accumulator / len(sources), -1, 1),
        dtype=np.float32,
    )
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = output.with_name(f".{output.name}.{os.getpid()}.tmp.wav")
    try:
        sf.write(
            temporary,
            aggregate,
            master_info.samplerate,
            format="WAV",
            subtype="FLOAT",
        )
        os.replace(temporary, output)
    finally:
        temporary.unlink(missing_ok=True)
    return output


def _relative_path(path: Path, root: Path) -> str:
    return Path(os.path.relpath(path.resolve(), root.resolve())).as_posix()


def _background_image_inputs(
    document: TrackProjectDocument,
    workspace: TrackWorkspace,
    cover_path: Path,
) -> dict[str, Path]:
    project_root = workspace.project_path.parent.resolve()
    values = {
        "video.background.image": document.project.video.background.image,
        **{
            f"visuals.background_overrides.{section_id}.image": background.image
            for section_id, background in document.project.visuals.background_overrides.items()
        },
    }
    resolved: dict[str, Path] = {}
    for label, value in values.items():
        if value is None:
            continue
        if value.as_posix() == "@mrp/cover":
            resolved[label] = cover_path
            continue
        path = (project_root / value).resolve()
        try:
            path.relative_to(project_root)
        except ValueError as exc:
            raise MRPVideoAdapterError(
                f"{label} must stay inside {project_root} or use @mrp/cover"
            ) from exc
        if not path.is_file():
            raise MRPVideoAdapterError(
                f"{label} does not exist or is not a file: {path}"
            )
        resolved[label] = path
    return resolved


def _runtime_project(
    document: TrackProjectDocument,
    workspace: TrackWorkspace,
    *,
    master_path: Path,
    semantic_paths: dict[str, Path],
    cover_path: Path,
    font_path: Path,
    background_paths: dict[str, Path],
) -> ProjectManifest:
    payload = document.project.model_dump(mode="json", exclude_none=True)
    root = workspace.runtime_manifest_path.parent
    payload["audio"] = {
        "master": _relative_path(master_path, root),
        "stems": {
            role: _relative_path(path, root)
            for role, path in sorted(semantic_paths.items())
        },
        "duration_tolerance": document.project.audio.duration_tolerance,
    }
    payload["lyrics"]["source"] = workspace.runtime_lyrics_path.name
    payload["lyrics"]["aligned"] = _relative_path(workspace.aligned_path, root)
    payload["cards"]["opening"]["file"] = _relative_path(cover_path, root)
    payload["cards"]["closing"]["file"] = _relative_path(cover_path, root)
    track_background = background_paths.get("video.background.image")
    if track_background is not None:
        payload["video"]["background"]["image"] = _relative_path(
            track_background,
            root,
        )
    for section_id, background in payload["visuals"].get(
        "background_overrides",
        {},
    ).items():
        source = background_paths.get(
            f"visuals.background_overrides.{section_id}.image"
        )
        if source is not None:
            background["image"] = _relative_path(source, root)
    payload["text"]["font"] = _relative_path(font_path, root)
    return ProjectManifest.model_validate(payload)


def _artifact_states(
    workspace: TrackWorkspace,
    fingerprint: str,
) -> tuple[dict[str, Any], ...]:
    if not workspace.artifact_index_path.is_file():
        return ()
    value = json.loads(workspace.artifact_index_path.read_text(encoding="utf-8"))
    artifacts = value.get("artifacts") if isinstance(value, dict) else None
    if not isinstance(artifacts, list):
        raise MRPVideoAdapterError(
            f"invalid artifact index: {workspace.artifact_index_path}"
        )
    return tuple(
        {
            **artifact,
            "stale": artifact.get("input_fingerprint") != fingerprint,
        }
        for artifact in artifacts
        if isinstance(artifact, dict)
    )


def _record_artifact(
    prepared: PreparedTrack,
    *,
    kind: str,
    path: Path,
    details: dict[str, Any],
) -> None:
    index_path = prepared.workspace.artifact_index_path
    if index_path.is_file():
        value = json.loads(index_path.read_text(encoding="utf-8"))
    else:
        value = {"version": 1, "artifacts": []}
    artifacts = value.setdefault("artifacts", [])
    artifact_path = prepared.workspace.relative(path)
    artifacts[:] = [
        artifact
        for artifact in artifacts
        if not (
            isinstance(artifact, dict)
            and artifact.get("kind") == kind
            and artifact.get("path") == artifact_path
        )
    ]
    artifacts.append(
        {
            "kind": kind,
            "path": artifact_path,
            "input_fingerprint": prepared.input_fingerprint,
            "recorded_at": datetime.now(UTC).isoformat(),
            "details": details,
        }
    )
    _write_json(index_path, value)


def _advance_preview_status(
    repo: Path,
    release_slug: str,
    track_slug: str | None,
) -> None:
    """Advance only an explicitly cast track after a current preview succeeds."""
    selection = _select_track(repo, release_slug, track_slug)
    current = selection.track.get("music_video")
    if not isinstance(current, dict):
        return
    if current.get("status") not in {"cast", "previewed"}:
        return
    video = dict(current)
    video["status"] = "previewed"
    selection.track["music_video"] = video
    _write_yaml(selection.release_path, selection.document)
    preflight = TrackWorkspace.for_track(
        selection.repo,
        selection.track_key,
    ).preflight_path
    if preflight.is_file():
        os.utime(preflight, None)


def _advance_render_status(
    repo: Path,
    release_slug: str,
    track_slug: str | None,
) -> None:
    """Advance a current cast/preview only after a verified full render succeeds."""
    selection = _select_track(repo, release_slug, track_slug)
    current = selection.track.get("music_video")
    if not isinstance(current, dict):
        return
    if current.get("status") not in {"cast", "previewed", "rendered"}:
        return
    video = dict(current)
    video["status"] = "rendered"
    selection.track["music_video"] = video
    _write_yaml(selection.release_path, selection.document)
    preflight = TrackWorkspace.for_track(
        selection.repo,
        selection.track_key,
    ).preflight_path
    if preflight.is_file():
        os.utime(preflight, None)


def _render_output(
    prepared: PreparedTrack,
    *,
    draft: bool,
    render_id: str | None,
) -> tuple[Path, str | None]:
    if render_id is None and draft:
        render_id = datetime.now(UTC).strftime("%Y%m%dT%H%M%S%fZ")
    if render_id is not None:
        if not _RENDER_ID_PATTERN.fullmatch(render_id):
            raise MRPVideoAdapterError(
                "render id must contain only letters, digits, underscore, or hyphen"
            )
        directory = "drafts" if draft else "full"
        return prepared.workspace.renders_dir / directory / f"{render_id}.mp4", render_id
    return prepared.workspace.renders_dir / f"{prepared.track_key}.mp4", None


def prepare_track(
    repo: Path,
    release_slug: str,
    track_slug: str | None = None,
    *,
    font_path: Path | None = None,
    force_project: bool = False,
    update_release: bool = True,
    require_tools: bool = True,
    probe_media: bool = True,
) -> PreparedTrack:
    selection = _select_track(repo, release_slug, track_slug)
    workspace = TrackWorkspace.for_track(selection.repo, selection.track_key)
    workspace.ensure_generated_dirs()
    groups = _stem_groups(selection)
    document = _source_project(
        selection,
        groups,
        workspace,
        force=force_project,
    )
    _link_release_project(
        selection,
        workspace,
        update_release=False,
    )

    master_value = selection.track.get("master_path")
    if not master_value:
        raise MRPVideoAdapterError("track master_path is required for video work")
    master_path = _resolve_input(selection.repo, str(master_value), "track master")
    cover_value = selection.release.get("cover_image")
    if not cover_value:
        raise MRPVideoAdapterError("release cover_image is required for video cards")
    cover_path = _resolve_input(selection.repo, str(cover_value), "release cover")
    resolved_font = _default_font(font_path)
    background_paths = _background_image_inputs(document, workspace, cover_path)

    lyrics, lyric_directions = _structured_lyrics(selection)
    _write_yaml(
        workspace.runtime_lyrics_path,
        lyrics.model_dump(mode="json", exclude_none=True),
    )
    input_paths: dict[str, Path] = {
        "audio.master": master_path,
        "lyrics.source": workspace.runtime_lyrics_path,
        "cards.cover": cover_path,
        "text.font": resolved_font,
        **background_paths,
    }
    stem_hashes: dict[str, str] = {}
    for sources in groups.values():
        for source in sources:
            label = f"audio.stem.{source.id}"
            input_paths[label] = source.path
            stem_hashes[source.id] = _hash_file(source.path)
    if workspace.aligned_path.is_file():
        input_paths["lyrics.aligned"] = workspace.aligned_path
    input_hashes = {label: _hash_file(path) for label, path in input_paths.items()}

    if probe_media:
        master_source_duration = _audio_duration(master_path, "track master")
        tolerance = document.project.audio.duration_tolerance
        duration_problems = []
        for sources in groups.values():
            for source in sources:
                duration = _audio_duration(source.path, f"stem {source.id}")
                difference = abs(duration - master_source_duration)
                if difference > tolerance:
                    duration_problems.append(
                        f"stem {source.id} duration differs from the master by "
                        f"{difference:.3f}s (tolerance {tolerance:.3f}s)"
                    )
        if duration_problems:
            raise MRPVideoAdapterError(*duration_problems)

    semantic_paths = {
        role: _aggregate_stems(
            workspace,
            role,
            sources,
            source_hashes=stem_hashes,
            master_path=master_path,
        )
        for role, sources in groups.items()
    }
    runtime_project = _runtime_project(
        document,
        workspace,
        master_path=master_path,
        semantic_paths=semantic_paths,
        cover_path=cover_path,
        font_path=resolved_font,
        background_paths=background_paths,
    )
    _write_yaml(
        workspace.runtime_manifest_path,
        runtime_project.model_dump(mode="json", exclude_none=True),
    )

    project_hash = _hash_file(workspace.project_path)
    input_fingerprint = _fingerprint(project_hash, input_hashes)
    try:
        with Image.open(cover_path) as image:
            image.verify()
        ImageFont.truetype(str(resolved_font), document.project.text.size)
        validation = validate_project(
            workspace.runtime_manifest_path,
            require_tools=require_tools,
            probe_media=probe_media,
        )
    except (
        OSError,
        RuntimeError,
        SpirophonicValidationError,
        ValidationError,
    ) as exc:
        problems = exc.problems if isinstance(exc, SpirophonicValidationError) else (str(exc),)
        _write_json(
            workspace.preflight_path,
            {
                "version": 1,
                "status": "failed",
                "track_key": selection.track_key,
                "input_fingerprint": input_fingerprint,
                "errors": list(problems),
            },
        )
        raise MRPVideoAdapterError(*problems) from exc

    stale = _artifact_states(workspace, input_fingerprint)
    prepared = PreparedTrack(
        release_slug=selection.release_slug,
        track_slug=selection.track_slug,
        track_title=str(selection.track.get("title") or selection.track_slug),
        track_key=selection.track_key,
        workspace=workspace,
        runtime_manifest_path=workspace.runtime_manifest_path,
        project_hash=project_hash,
        input_hashes=input_hashes,
        input_fingerprint=input_fingerprint,
        aggregation={
            role: tuple(source.id for source in sources)
            for role, sources in groups.items()
        },
        stale_artifacts=tuple(item for item in stale if item["stale"]),
        master_duration=validation.master_duration,
        stem_durations=validation.stem_durations,
        lyric_directions=lyric_directions,
    )
    _link_release_project(
        selection,
        workspace,
        update_release=update_release,
    )
    _write_json(workspace.preflight_path, {"version": 1, **prepared.summary()})
    return prepared


def analyze_track(
    repo: Path,
    release_slug: str,
    track_slug: str | None = None,
    *,
    font_path: Path | None = None,
    force: bool = False,
    progress: Callable[[str], None] | None = None,
) -> dict[str, Any]:
    prepared = prepare_track(repo, release_slug, track_slug, font_path=font_path)
    try:
        run = analyze_project(
            prepared.runtime_manifest_path,
            force=force,
            progress=progress,
        )
    except (SpirophonicValidationError, SpirophonicAnalysisError) as exc:
        raise MRPVideoAdapterError(str(exc)) from exc
    _record_artifact(
        prepared,
        kind="analysis",
        path=run.cache_path,
        details=run.summary(),
    )
    return {"preflight": prepared.summary(), "analysis": run.summary()}


def align_track(
    repo: Path,
    release_slug: str,
    track_slug: str | None = None,
    *,
    font_path: Path | None = None,
    force: bool = False,
    retranscribe: bool = False,
    client: Any | None = None,
    progress: Callable[[str], None] | None = None,
) -> dict[str, Any]:
    prepared = prepare_track(repo, release_slug, track_slug, font_path=font_path)
    try:
        run = align_project(
            prepared.runtime_manifest_path,
            force=force,
            retranscribe=retranscribe,
            client=client,
            progress=progress,
        )
    except (
        SpirophonicValidationError,
        SpirophonicAnalysisError,
        SpirophonicAlignmentError,
    ) as exc:
        raise MRPVideoAdapterError(str(exc)) from exc
    refreshed = prepare_track(repo, release_slug, track_slug, font_path=font_path)
    _record_artifact(
        refreshed,
        kind="alignment",
        path=run.output_path,
        details=run.summary(),
    )
    return {"preflight": refreshed.summary(), "alignment": run.summary()}


def preview_track(
    repo: Path,
    release_slug: str,
    track_slug: str | None = None,
    *,
    font_path: Path | None = None,
    time_seconds: float = 0,
    draft: bool = True,
    force: bool = False,
) -> dict[str, Any]:
    prepared = prepare_track(repo, release_slug, track_slug, font_path=font_path)
    output = prepared.workspace.previews_dir / f"frame-{time_seconds:.3f}.png"
    try:
        context = load_render_context(prepared.runtime_manifest_path)
        result = render_frame_file(
            context,
            output,
            time_seconds=time_seconds,
            draft=draft,
            force=force,
        )
    except (
        SpirophonicValidationError,
        SpirophonicAnalysisError,
        SpirophonicRendererError,
    ) as exc:
        raise MRPVideoAdapterError(str(exc)) from exc
    _record_artifact(
        prepared,
        kind="preview",
        path=result.output_path,
        details={"preview_type": "frame", **result.summary()},
    )
    _advance_preview_status(repo, release_slug, track_slug)
    return {"preflight": prepared.summary(), "preview": result.summary()}


def contact_sheet_track(
    repo: Path,
    release_slug: str,
    track_slug: str | None = None,
    *,
    font_path: Path | None = None,
    columns: int = 3,
    force: bool = False,
    progress: Callable[[str], None] | None = None,
) -> dict[str, Any]:
    """Render one deterministic representative frame for every lyric section."""
    if columns < 1 or columns > 6:
        raise MRPVideoAdapterError("contact-sheet columns must be between 1 and 6")
    prepared = prepare_track(repo, release_slug, track_slug, font_path=font_path)
    output = prepared.workspace.previews_dir / "contact-sheet.png"
    if output.exists() and not force:
        raise MRPVideoAdapterError(
            f"contact sheet already exists: {output}; use --force to overwrite"
        )
    try:
        context = load_render_context(prepared.runtime_manifest_path, progress=progress)
        width, height, fps = render_dimensions(context.project, draft=True)
        thumb_width = min(360, width)
        thumb_height = max(1, round(height * thumb_width / width))
        label_height = 34
        gutter = 12
        sections = list(context.lyrics.sections)
        rows = (len(sections) + columns - 1) // columns
        sheet = Image.new(
            "RGB",
            (
                gutter + columns * (thumb_width + gutter),
                gutter + rows * (thumb_height + label_height + gutter),
            ),
            context.project.video.background.color,
        )
        draw = ImageDraw.Draw(sheet)
        font = ImageFont.load_default()
        cells: list[dict[str, Any]] = []
        for index, section in enumerate(sections):
            if progress is not None:
                progress(
                    f"Rendering contact-sheet section {index + 1} of {len(sections)}"
                )
            requested_time = section.start + (section.end - section.start) / 2
            frame_index = round(requested_time * fps)
            time_seconds = min(frame_index / fps, context.analysis.duration)
            frame = render_frame(
                context,
                time_seconds,
                frame_index,
                width=width,
                height=height,
            )
            image = Image.fromarray(frame, mode="RGB")
            if image.size != (thumb_width, thumb_height):
                image = image.resize(
                    (thumb_width, thumb_height),
                    Image.Resampling.LANCZOS,
                )
            column = index % columns
            row = index // columns
            left = gutter + column * (thumb_width + gutter)
            top = gutter + row * (thumb_height + label_height + gutter)
            sheet.paste(image, (left, top))
            label = section.label or section.type.replace("_", " ").title()
            draw.text(
                (left + 4, top + thumb_height + 8),
                f"{label}  {time_seconds:.3f}s",
                fill="#ffffff",
                font=font,
            )
            cells.append(
                {
                    "section_id": section.id,
                    "section_type": section.type,
                    "time_seconds": time_seconds,
                    "frame_index": frame_index,
                }
            )
        temporary = output.with_name(f".{output.name}.{os.getpid()}.tmp")
        try:
            sheet.save(temporary, format="PNG", optimize=True)
            os.replace(temporary, output)
        finally:
            temporary.unlink(missing_ok=True)
    except (
        OSError,
        SpirophonicValidationError,
        SpirophonicAnalysisError,
        SpirophonicRendererError,
    ) as exc:
        raise MRPVideoAdapterError(str(exc)) from exc
    summary = {
        "output_path": str(output),
        "section_count": len(cells),
        "columns": columns,
        "width": sheet.width,
        "height": sheet.height,
        "cells": cells,
    }
    _record_artifact(
        prepared,
        kind="preview",
        path=output,
        details={"preview_type": "contact_sheet", **summary},
    )
    _advance_preview_status(repo, release_slug, track_slug)
    return {"preflight": prepared.summary(), "contact_sheet": summary}


def render_track(
    repo: Path,
    release_slug: str,
    track_slug: str | None = None,
    *,
    font_path: Path | None = None,
    draft: bool = False,
    start_seconds: float | None = None,
    end_seconds: float | None = None,
    force: bool = False,
    dry_run: bool = False,
    render_id: str | None = None,
    expected_fingerprint: str | None = None,
    progress: Callable[[str], None] | None = None,
    cancel_check: Callable[[], bool] | None = None,
) -> dict[str, Any]:
    prepared = prepare_track(repo, release_slug, track_slug, font_path=font_path)
    if (
        expected_fingerprint is not None
        and prepared.input_fingerprint != expected_fingerprint
    ):
        raise MRPVideoAdapterError(
            "render inputs changed after full-render preflight; run preflight again"
        )
    output, resolved_render_id = _render_output(
        prepared,
        draft=draft,
        render_id=render_id,
    )
    try:
        if dry_run:
            plan = plan_project_video(
                prepared.runtime_manifest_path,
                draft=draft,
                start_seconds=start_seconds,
                end_seconds=end_seconds,
                progress=progress,
            )
            return {
                "preflight": prepared.summary(),
                "render_plan": {"output_path": prepared.workspace.relative(output), **plan.summary()},
            }
        run = render_project_video(
            prepared.runtime_manifest_path,
            output,
            draft=draft,
            start_seconds=start_seconds,
            end_seconds=end_seconds,
            force=force,
            progress=progress,
            cancel_check=cancel_check,
        )
    except (
        SpirophonicValidationError,
        SpirophonicAnalysisError,
        SpirophonicRendererError,
        SpirophonicCardError,
        SpirophonicEncodingError,
        SpirophonicVerificationError,
        SpirophonicManifestError,
        SpirophonicPipelineError,
    ) as exc:
        raise MRPVideoAdapterError(str(exc)) from exc
    _record_artifact(
        prepared,
        kind="draft" if draft else "render",
        path=run.output_path,
        details={"render_id": resolved_render_id, **run.summary()},
    )
    if not draft:
        _advance_render_status(repo, release_slug, track_slug)
    return {"preflight": prepared.summary(), "render": run.summary()}
