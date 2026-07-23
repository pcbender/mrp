"""Versioned section-casting edits for the per-track Video workspace."""
from __future__ import annotations

import json
import hashlib
import math
import os
import re
from pathlib import Path
from typing import Any, Mapping, Sequence

import yaml
from pydantic import ValidationError

from mrp.admin.video_workspace import track_key

STYLE_NUMBER_FIELDS = (
    "layer_fraction",
    "scale",
    "motion",
    "color_intensity",
    "onset_response",
    "rotation_direction",
    "palette_shift",
    "lyrics_opacity",
    "spatial_spread",
    "anchor_drift",
    "trace_speed",
    "trail_length",
    "beat_gain",
    "intensity_gain",
)


class CastingEditorError(Exception):
    def __init__(self, *problems: str):
        self.problems = tuple(problems)
        super().__init__("; ".join(problems))


def project_path(root: Path, release: dict[str, Any], track: dict[str, Any]) -> Path:
    return (
        root
        / "assets"
        / "source"
        / "video"
        / track_key(release, track)
        / "project.yaml"
    )


def aligned_path(root: Path, release: dict[str, Any], track: dict[str, Any]) -> Path:
    return project_path(root, release, track).with_name("lyrics.aligned.yaml")


def previews_path(root: Path, release: dict[str, Any], track: dict[str, Any]) -> Path:
    return (
        root
        / "assets"
        / "processed"
        / "video"
        / track_key(release, track)
        / "previews"
    )


def _preflight_path(root: Path, release: dict[str, Any], track: dict[str, Any]) -> Path:
    return previews_path(root, release, track).parent / "logs" / "preflight.json"


def _artifact_path(root: Path, release: dict[str, Any], track: dict[str, Any]) -> Path:
    return previews_path(root, release, track).parent / "logs" / "artifacts.json"


def _read_mapping(path: Path) -> dict[str, Any]:
    try:
        value = yaml.safe_load(path.read_text(encoding="utf-8"))
    except OSError as exc:
        raise CastingEditorError(f"cannot read {path}: {exc}") from exc
    except yaml.YAMLError as exc:
        raise CastingEditorError(f"malformed YAML in {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise CastingEditorError(f"{path} must contain a YAML mapping")
    return value


def _load_project(path: Path):
    from mrp.video.track_project import TrackProjectDocument

    if not path.is_file():
        raise CastingEditorError("video project does not exist; run prepare first")
    try:
        return TrackProjectDocument.model_validate(_read_mapping(path))
    except ValidationError as exc:
        raise CastingEditorError(*_validation_problems(exc)) from exc


def _load_lyrics(path: Path):
    from mrp.video.project import SpirophonicValidationError, load_aligned_lyrics

    if not path.is_file():
        raise CastingEditorError("aligned lyrics do not exist; finish timing first")
    try:
        return load_aligned_lyrics(path)
    except SpirophonicValidationError as exc:
        raise CastingEditorError(*exc.problems) from exc


def _validation_problems(exc: ValidationError) -> tuple[str, ...]:
    problems = []
    for error in exc.errors(include_url=False):
        location = ".".join(str(part) for part in error["loc"]) or "document"
        problems.append(f"{location}: {error['msg']}")
    return tuple(problems)


def _casefold_item(values: Mapping[str, Any], key: str) -> tuple[str, Any] | None:
    folded = key.casefold()
    return next(
        ((name, value) for name, value in values.items() if name.casefold() == folded),
        None,
    )


def actor_library_path(root: Path) -> Path:
    return root / "assets" / "source" / "video" / "actors"


def _actor_revision(actor: Any) -> str:
    payload = actor.model_dump(mode="json", exclude_none=True)
    payload.pop("library_source", None)
    payload.pop("character", None)
    encoded = json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _library_actors(root: Path) -> list[dict[str, Any]]:
    from mrp.video.project import ActorLibraryDocument

    library = actor_library_path(root)
    if not library.is_dir():
        return []
    actors = []
    for path in sorted(library.glob("*.yaml")):
        try:
            document = ActorLibraryDocument.model_validate(_read_mapping(path))
        except CastingEditorError:
            raise
        except ValidationError as exc:
            raise CastingEditorError(
                *[f"actor library {path.name}: {problem}" for problem in _validation_problems(exc)]
            ) from exc
        actor = document.actor
        actors.append(
            {
                "actor": actor,
                "id": actor.id,
                "name": actor.name,
                "description": actor.description,
                "revision": _actor_revision(actor),
                "path": path.relative_to(root).as_posix(),
            }
        )
    return actors


def _write_library_actor(root: Path, actor: Any) -> dict[str, Any]:
    from mrp.video.project import ActorLibraryDocument

    clean_actor = actor.model_copy(
        update={"character": None, "library_source": None}
    )
    document = ActorLibraryDocument(actor=clean_actor)
    directory = actor_library_path(root)
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / f"{clean_actor.id}.yaml"
    _write_yaml_atomic(
        path,
        document.model_dump(mode="json", exclude_none=True),
    )
    return {
        "actor": clean_actor,
        "id": clean_actor.id,
        "name": clean_actor.name,
        "description": clean_actor.description,
        "revision": _actor_revision(clean_actor),
        "path": path.relative_to(root).as_posix(),
    }


def list_library_actors(root: Path) -> list[dict[str, Any]]:
    """Public view of the reusable actor library for the Actor Designer."""
    return _library_actors(root)


def library_actor(root: Path, actor_id: str) -> dict[str, Any] | None:
    return next(
        (entry for entry in _library_actors(root) if entry["id"] == actor_id),
        None,
    )


def split_svg_subpaths(text: str, *, limit: int = 9) -> list[dict[str, Any]]:
    """Split SVG markup or a bare ``d`` attribute into single-subpath entries.

    The split happens server-side because browsers expose no subpath
    enumeration, and re-serializing each subpath through svgpathtools
    resolves the relative-``m`` continuation trap (an ``m`` after a drawn
    segment continues from the previous point, so a subpath's commands are
    not independent of the ones before it). Returns up to ``limit`` entries
    (matching ActorConfig's 9-component cap) shaped for the designer
    importer: the subpath's absolute ``d`` string and whether it closes.
    """
    try:
        from svgpathtools import parse_path
        from svgpathtools.svg_to_paths import (
            ellipse2pathd,
            polyline2pathd,
            rect2pathd,
        )
    except ImportError as exc:  # pragma: no cover - environment guard
        raise CastingEditorError(
            "svg import requires svgpathtools; install requirements-video.txt"
        ) from exc

    source = text.strip()
    if not source:
        raise CastingEditorError("svg import requires SVG markup or path data")
    attributes: list[str] = []
    if source.startswith("<"):
        import xml.etree.ElementTree as ElementTree

        try:
            root = ElementTree.fromstring(source)
        except ElementTree.ParseError as exc:
            raise CastingEditorError(f"svg import could not parse the markup: {exc}") from exc
        # Basic shapes convert through svgpathtools' own helpers so imported
        # marks (circles, rounded rects, polygons) trace like hand-written
        # paths; root.iter() preserves document order for stacking.
        for element in root.iter():
            tag = element.tag.rsplit("}", 1)[-1]
            try:
                if tag == "path":
                    data = (element.get("d") or "").strip()
                elif tag in {"circle", "ellipse"}:
                    data = ellipse2pathd(element.attrib)
                elif tag == "rect":
                    data = rect2pathd(element.attrib)
                elif tag == "polygon":
                    data = polyline2pathd(element.attrib, is_polygon=True)
                elif tag == "polyline":
                    data = polyline2pathd(element.attrib, is_polygon=False)
                elif tag == "line":
                    data = "M {x1} {y1} L {x2} {y2}".format(
                        x1=float(element.get("x1", "0")),
                        y1=float(element.get("y1", "0")),
                        x2=float(element.get("x2", "0")),
                        y2=float(element.get("y2", "0")),
                    )
                else:
                    continue
            except (KeyError, ValueError) as exc:
                raise CastingEditorError(
                    f"svg import could not convert a <{tag}> element: {exc}"
                ) from exc
            if data:
                attributes.append(data)
        if not attributes:
            raise CastingEditorError(
                "svg import found no drawable elements (path, circle, ellipse, "
                "rect, polygon, polyline, line)"
            )
    else:
        attributes.append(source)

    subpaths: list[dict[str, Any]] = []
    samples: list[tuple[list[float], list[float]]] = []
    for data in attributes:
        if len(subpaths) >= limit:
            break
        try:
            parsed = parse_path(data)
        except Exception as exc:
            raise CastingEditorError(f"svg import could not parse path data: {exc}") from exc
        for subpath in parsed.continuous_subpaths():
            if not len(subpath):
                continue
            start, end = subpath.start, subpath.end
            xmin, xmax, ymin, ymax = subpath.bbox()
            diagonal = math.hypot(xmax - xmin, ymax - ymin)
            closed = bool(subpath.isclosed()) or (
                diagonal > 0 and abs(end - start) < 1e-6 * diagonal
            )
            subpaths.append({"d": subpath.d(), "closed": closed})
            points = [subpath.point(index / 127) for index in range(128)]
            samples.append(([p.real for p in points], [p.imag for p in points]))
            if len(subpaths) >= limit:
                break
    if not subpaths:
        raise CastingEditorError("svg import found no drawable subpaths")
    _apply_source_layout(subpaths, samples)
    return subpaths


# Mirrors MARGIN in static/spiro-preview.js — keep the two in sync.
_PREVIEW_MARGIN = 0.08


def _apply_source_layout(
    entries: list[dict[str, Any]],
    samples: list[tuple[list[float], list[float]]],
) -> None:
    """Anchor/scale hints that reconstruct the source SVG's composition.

    The designer draws each path component centered on its own bounding box
    and sized by base_scale/extent (mrpDrawShapes in static/spiro-preview.js),
    so a multi-shape import would otherwise scatter across the default anchor
    grid. These hints map every subpath's center and extent back onto that
    draw law so the imported components reproduce the source layout: anchors
    place each shape's center relative to the union bounds, base_scale keeps
    the shapes' relative sizes.
    """
    all_x = [value for xs, _ in samples for value in xs]
    all_y = [value for _, ys in samples for value in ys]
    if not all_x:
        return
    union_cx = (max(all_x) + min(all_x)) / 2
    union_cy = (max(all_y) + min(all_y)) / 2
    radius = max(max(all_x) - min(all_x), max(all_y) - min(all_y)) / 2
    if radius <= 0:
        return
    factor = 0.5 - _PREVIEW_MARGIN
    for entry, (xs, ys) in zip(entries, samples):
        cx = (max(xs) + min(xs)) / 2
        cy = (max(ys) + min(ys)) / 2
        extent = max(
            (math.hypot(x - cx, y - cy) for x, y in zip(xs, ys)),
            default=0.0,
        )
        # Steps match the component form inputs: anchors 0.001, scale 0.01.
        entry["anchor_x"] = round(
            min(1.5, max(-0.5, 0.5 + factor * (cx - union_cx) / radius)), 3
        )
        entry["anchor_y"] = round(
            min(1.5, max(-0.5, 0.5 + factor * (cy - union_cy) / radius)), 3
        )
        entry["base_scale"] = round(min(2.0, max(0.05, extent / radius)), 2)


def actor_preview_shapes(actor: Any) -> list[dict[str, Any]]:
    """Draw-ready component shapes for the shared canvas helpers."""
    return [_storyboard_shape(component) for component in actor.components]


def _delete_library_actor(root: Path, actor_id: str, *, missing_ok: bool = False) -> None:
    directory = actor_library_path(root)
    path = directory / f"{_slug(actor_id)}.yaml"
    if not path.is_file():
        if missing_ok:
            return
        raise CastingEditorError(f"library actor does not exist: {actor_id}")
    path.unlink()


def _library_actor_payload(fields: Mapping[str, Sequence[str]]) -> dict[str, Any]:
    name = _single(fields, "actor_name")
    if not name:
        raise CastingEditorError("actor name is required")
    actor_id = _slug(_single(fields, "actor_edit_id", default="") or name)
    return {
        "id": actor_id,
        "name": name,
        "description": _single(fields, "actor_description", default=""),
        "kind": "spirogram",
        "components": _trace_payloads(fields),
    }


def save_library_actor(root: Path, fields: Mapping[str, Sequence[str]]) -> str:
    """Apply one Actor Designer action to the global actor library.

    Library actors are freestanding YAML documents keyed by id; projects pin
    self-contained copies, so renames and deletes never touch a track project.
    Returns the resulting actor id ("" after a delete).
    """
    from mrp.video.project import ActorConfig

    action = _single(fields, "action")
    existing = {entry["id"]: entry for entry in _library_actors(root)}

    if action == "actor_save":
        payload = _library_actor_payload(fields)
        original_id = _single(fields, "actor_original_id", default="")
        if payload["id"] != original_id and payload["id"] in existing:
            raise CastingEditorError(
                f"the library already has an actor with id: {payload['id']}"
            )
        try:
            actor = ActorConfig.model_validate(payload)
        except ValidationError as exc:
            raise CastingEditorError(*_validation_problems(exc)) from exc
        entry = _write_library_actor(root, actor)
        if original_id and original_id != actor.id:
            # The library file is keyed by id, so a rename retires the old file.
            _delete_library_actor(root, original_id, missing_ok=True)
        return entry["id"]
    if action == "actor_duplicate":
        source_id = _single(fields, "actor_original_id")
        source = existing.get(source_id)
        if source is None:
            raise CastingEditorError(f"library actor does not exist: {source_id}")
        duplicate = source["actor"].model_copy(
            update={
                "id": _unique_actor_id(existing, f"{source_id}-copy"),
                "name": f"{source['name']} Copy",
            }
        )
        return _write_library_actor(root, duplicate)["id"]
    if action == "actor_delete":
        _delete_library_actor(root, _single(fields, "actor_original_id"))
        return ""
    raise CastingEditorError(f"unsupported actor action: {action}")


def _actor_cast_for_scope(project: Any, section: Any, scope: str):
    visuals = project.visuals
    if scope == "section":
        override = visuals.cast_overrides.get(section.id)
        if override is not None:
            return override.model_copy(deep=True), "exact scene actor cast"
    configured = _casefold_item(visuals.section_casts, section.type)
    if configured is not None:
        name, cast = configured
        return cast.model_copy(deep=True), f"actor cast for all {name} scenes"
    return None, "no actor cast"


def _slug(value: str, *, fallback: str = "actor") -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", value.casefold()).strip("-")
    return slug or fallback


def _unique_actor_id(actors: Mapping[str, Any], preferred: str) -> str:
    candidate = _slug(preferred)
    if candidate not in actors:
        return candidate
    index = 2
    while f"{candidate}-{index}" in actors:
        index += 1
    return f"{candidate}-{index}"


def _actor_from_trace(trace: Any, actor_id: str | None = None):
    from mrp.video.project import ActorConfig

    identifier = actor_id or _slug(trace.id)
    component = trace.model_copy(update={"id": "shape"})
    return ActorConfig(
        id=identifier,
        name=trace.id.replace("-", " ").title(),
        character=trace.role,
        components=[component],
    )


def _selected_composition(project: Any, section: Any, scope: str):
    from mrp.video.casting import generate_auto_composition

    visuals = project.visuals
    if scope == "section":
        override = visuals.composition_overrides.get(section.id)
        if override is not None:
            return override.model_copy(deep=True), "section override"
    configured = _casefold_item(visuals.section_compositions, section.type)
    if configured is not None:
        name, composition = configured
        return composition.model_copy(deep=True), f"type default: {name}"
    return (
        generate_auto_composition(section.type, project.video.seed),
        f"deterministic auto: {section.type}",
    )


def _selected_style(project: Any, section: Any, scope: str):
    from mrp.video.project import SectionVisualStyleConfig

    if scope == "section":
        override = project.visuals.section_overrides.get(section.id)
        if override is not None:
            return override
    configured = _casefold_item(project.visuals.section_styles, section.type)
    if configured is not None:
        return configured[1]
    return SectionVisualStyleConfig()


def _gallery(
    root: Path,
    release: dict[str, Any],
    track: dict[str, Any],
) -> list[dict[str, Any]]:
    index_path = _artifact_path(root, release, track)
    preflight_path = _preflight_path(root, release, track)
    try:
        index = json.loads(index_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    try:
        preflight = json.loads(preflight_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        preflight = {}
    current_fingerprint = preflight.get("input_fingerprint")
    validation_current = preflight.get("status") == "passed"
    expected = previews_path(root, release, track).resolve()
    gallery = []
    for artifact in index.get("artifacts") or []:
        if not isinstance(artifact, dict) or artifact.get("kind") != "preview":
            continue
        value = artifact.get("path")
        if not isinstance(value, str):
            continue
        candidate = (root / value).resolve()
        try:
            candidate.relative_to(expected)
        except ValueError:
            continue
        if not candidate.is_file() or candidate.suffix.casefold() not in {".png", ".jpg", ".jpeg"}:
            continue
        details = artifact.get("details") if isinstance(artifact.get("details"), dict) else {}
        gallery.append(
            {
                "name": candidate.name,
                "recorded_at": artifact.get("recorded_at"),
                "preview_type": details.get("preview_type", "frame"),
                "time_seconds": details.get("time_seconds"),
                "section_count": details.get("section_count"),
                "stale": (
                    not validation_current
                    or not current_fingerprint
                    or artifact.get("input_fingerprint") != current_fingerprint
                ),
            }
        )
    return sorted(gallery, key=lambda item: str(item.get("recorded_at") or ""), reverse=True)


def _storyboard_shape(layer: Any) -> dict[str, Any]:
    """Serialize one visual layer's geometry and placement for canvas drawing."""
    return {
        # Whole geometry (family + its fields) so the client dispatcher draws
        # any curve family without per-field drift here.
        **layer.geometry.model_dump(mode="json", exclude_none=True),
        "samples": min(layer.geometry.samples, 1200),
        "color": layer.color,
        "color_flow": (
            {
                "source": layer.color_flow.source,
                "swing_degrees": layer.color_flow.swing_degrees,
            }
            if layer.color_flow is not None
            else None
        ),
        "anchor_x": layer.anchor_x,
        "anchor_y": layer.anchor_y,
        "base_scale": layer.base_scale,
        "opacity": layer.opacity,
        "line_width": layer.line_width,
        "depth": layer.depth,
    }


def _storyboard(composition: Any, background: str, actors: Any) -> dict[str, Any]:
    """Client-side draw data for the scene storyboard.

    ``traces`` is the compiled composition the renderer draws, so a scene shows
    its staged actors — or its legacy look — without a render job. ``actors``
    carries each project actor's identity components so the browser can recompile
    placement live from the direction fields as they are edited or dragged,
    matching ``compile_actor_cast``. The compiled trace id is
    ``{assignment}--{component}``; the assignment prefix maps a dragged shape
    back to its cast member. Legacy traces have no ``--`` and stay static.
    """
    traces = []
    for trace in composition.traces:
        shape = _storyboard_shape(trace)
        shape["id"] = trace.id
        shape["assignment"] = trace.id.split("--", 1)[0] if "--" in trace.id else None
        traces.append(shape)
    actor_identities = {
        actor_id: {
            "character": actor.character,
            "components": [_storyboard_shape(component) for component in actor.components],
        }
        for actor_id, actor in actors.items()
    }
    return {
        "background": background,
        "margin": 0.08,
        "traces": traces,
        "actors": actor_identities,
    }


def load_casting(
    root: Path,
    release: dict[str, Any],
    track: dict[str, Any],
    *,
    section_id: str | None = None,
    scope: str = "type",
    actor_id: str | None = None,
) -> dict[str, Any]:
    """Load one track's versioned casting project and resolved section scenes."""
    from mrp.video.casting import resolve_section_composition
    from mrp.video.presets import preset_catalog

    if scope not in {"type", "section"}:
        raise CastingEditorError("casting scope must be type or section")
    path = project_path(root, release, track)
    document = _load_project(path)
    lyrics = _load_lyrics(aligned_path(root, release, track))
    selected = next(
        (section for section in lyrics.sections if section.id == section_id),
        lyrics.sections[0],
    )
    library_actors = _library_actors(root)
    library_by_id = {entry["id"]: entry for entry in library_actors}
    project_actors = []
    for actor in sorted(document.project.visuals.actors.values(), key=lambda item: item.name.casefold()):
        source = actor.library_source
        library_entry = library_by_id.get(source.actor_id) if source is not None else None
        project_actors.append(
            {
                "actor": actor,
                "id": actor.id,
                "name": actor.name,
                "description": actor.description,
                "component_count": len(actor.components),
                "source": "library snapshot" if source is not None else "project actor",
                "library_status": (
                    "current"
                    if source is not None
                    and library_entry is not None
                    and _actor_revision(actor) == source.revision
                    and source.revision == library_entry["revision"]
                    else "modified"
                    if source is not None
                    and _actor_revision(actor) != source.revision
                    else "updated"
                    if source is not None and library_entry is not None
                    else "unavailable"
                    if source is not None
                    else None
                ),
            }
        )
    sections = []
    for section in lyrics.sections:
        resolved = resolve_section_composition(
            document.project.visuals,
            section.type,
            section.id,
            document.project.video.seed,
        )
        sections.append(
            {
                "id": section.id,
                "type": section.type,
                "label": section.label or section.type.replace("_", " ").title(),
                "start": section.start,
                "end": section.end,
                "midpoint": round(section.start + (section.end - section.start) / 2, 6),
                "composition_key": resolved.key,
                "trace_count": len(resolved.composition.traces),
                "actor_count": (
                    len(document.project.visuals.cast_overrides[section.id].actors)
                    if section.id in document.project.visuals.cast_overrides
                    else len(_casefold_item(document.project.visuals.section_casts, section.type)[1].actors)
                    if _casefold_item(document.project.visuals.section_casts, section.type) is not None
                    else 0
                ),
                "overridden": section.id in document.project.visuals.composition_overrides,
                "actor_overridden": section.id in document.project.visuals.cast_overrides,
            }
        )
    actor_cast, actor_cast_source = _actor_cast_for_scope(
        document.project,
        selected,
        scope,
    )
    if actor_cast is not None:
        from mrp.video.casting import compile_actor_cast

        composition = compile_actor_cast(document.project.visuals, actor_cast)
        composition_source = actor_cast_source
    else:
        composition, composition_source = _selected_composition(
            document.project,
            selected,
            scope,
        )
    new_actor_requested = actor_id == "__new__"
    selected_actor = (
        None
        if new_actor_requested
        else document.project.visuals.actors.get(actor_id or "")
    )
    selected_actor_saved = selected_actor is not None
    if selected_actor is None and project_actors and not new_actor_requested:
        selected_actor = project_actors[0]["actor"]
        selected_actor_saved = True
    if selected_actor is None:
        selected_actor = _actor_from_trace(
            composition.traces[0],
            _unique_actor_id(document.project.visuals.actors, "new-actor"),
        )
    style = _selected_style(document.project, selected, scope)
    return {
        "path": path.relative_to(root).as_posix(),
        "document": document,
        "project": document.project,
        "sections": sections,
        "selected_section": selected,
        "scope": scope,
        "composition": composition,
        "composition_source": composition_source,
        "actor_cast": actor_cast,
        "actor_cast_source": actor_cast_source,
        "storyboard": _storyboard(
            composition,
            document.project.video.background,
            document.project.visuals.actors,
        ),
        "project_actors": project_actors,
        "library_actors": library_actors,
        "selected_actor": selected_actor,
        "selected_actor_saved": selected_actor_saved,
        "style": style,
        "presets": preset_catalog(),
        "gallery": _gallery(root, release, track),
    }


def _single(
    fields: Mapping[str, Sequence[str]],
    name: str,
    *,
    default: str | None = None,
) -> str:
    values = [str(value) for value in fields.get(name, [])]
    if not values and default is not None:
        return default
    if len(values) != 1:
        raise CastingEditorError(f"{name} supplied {len(values)} values; expected 1")
    return values[0].strip()


def _repeated(
    fields: Mapping[str, Sequence[str]],
    name: str,
    count: int,
) -> list[str]:
    values = [str(value).strip() for value in fields.get(name, [])]
    if len(values) != count:
        raise CastingEditorError(f"{name} supplied {len(values)} values; expected {count}")
    return values


def _number(value: str, label: str) -> float:
    try:
        number = float(value)
    except ValueError as exc:
        raise CastingEditorError(f"{label} must be a number") from exc
    if not math.isfinite(number):
        raise CastingEditorError(f"{label} must be finite")
    return round(number, 6)


def _integer(value: str, label: str) -> int:
    try:
        number = int(value)
    except ValueError as exc:
        raise CastingEditorError(f"{label} must be an integer") from exc
    return number


def _optional_number(value: str, label: str) -> float | None:
    return None if not value else _number(value, label)


def _trace_payloads(fields: Mapping[str, Sequence[str]]) -> list[dict[str, Any]]:
    ids = [str(value).strip() for value in fields.get("trace_id", [])]
    if not ids:
        raise CastingEditorError("a manual cast requires at least one trace")
    count = len(ids)
    names = (
        "trace_role",
        "geometry_family",
        "fixed_radius",
        "moving_radius",
        "pen_offset",
        "phase",
        "geometry_rotation",
        "samples",
        "liss_freq_x",
        "liss_freq_y",
        "liss_delta",
        "rose_n",
        "rose_d",
        "sf_m",
        "sf_n1",
        "sf_n2",
        "sf_n3",
        "path_data",
        "harm_freq_x",
        "harm_freq_y",
        "harm_delta",
        "harm_damping",
        "harm_turns",
        "cycles_per_second",
        "trail_fraction",
        "ghost_count",
        "ghost_spacing",
        "head_radius",
        "color",
        "depth",
        "anchor_x",
        "anchor_y",
        "base_scale",
        "opacity",
        "line_width",
        "rotation_speed",
        "hue_shift",
        "blend_mode",
        "color_flow_source",
        "color_flow_swing",
        "driver_scale",
        "driver_opacity",
        "driver_color",
        "driver_pulse",
    )
    columns = {name: _repeated(fields, name, count) for name in names}
    traces = []
    for index, trace_id in enumerate(ids):
        drivers = {
            key.removeprefix("driver_"): columns[key][index]
            for key in ("driver_scale", "driver_opacity", "driver_color", "driver_pulse")
            if columns[key][index]
        }
        flow_source = columns["color_flow_source"][index]
        color_flow = (
            {
                "source": flow_source,
                "swing_degrees": _number(
                    columns["color_flow_swing"][index],
                    f"trace {trace_id} color flow swing",
                ),
            }
            if flow_source
            else None
        )
        family = columns["geometry_family"][index] or "spirogram"
        geometry: dict[str, Any] = {
            "family": family,
            "phase": _number(columns["phase"][index], f"trace {trace_id} phase"),
            "samples": _integer(columns["samples"][index], f"trace {trace_id} samples"),
        }
        # Only the active family's columns are parsed, so hidden inputs left
        # blank by the form can never fail number validation.
        if family == "spirogram":
            geometry |= {
                "fixed_radius": _number(columns["fixed_radius"][index], f"trace {trace_id} fixed radius"),
                "moving_radius": _number(columns["moving_radius"][index], f"trace {trace_id} moving radius"),
                "pen_offset": _number(columns["pen_offset"][index], f"trace {trace_id} pen offset"),
                "rotation": columns["geometry_rotation"][index],
            }
        elif family == "lissajous":
            geometry |= {
                "liss_freq_x": _integer(columns["liss_freq_x"][index], f"trace {trace_id} x frequency"),
                "liss_freq_y": _integer(columns["liss_freq_y"][index], f"trace {trace_id} y frequency"),
                "liss_delta": _number(columns["liss_delta"][index], f"trace {trace_id} delta"),
            }
        elif family == "rose":
            geometry |= {
                "rose_n": _integer(columns["rose_n"][index], f"trace {trace_id} petal numerator"),
                "rose_d": _integer(columns["rose_d"][index], f"trace {trace_id} petal denominator"),
            }
        elif family == "superformula":
            geometry |= {
                "sf_m": _integer(columns["sf_m"][index], f"trace {trace_id} symmetry m"),
                "sf_n1": _number(columns["sf_n1"][index], f"trace {trace_id} n1"),
                "sf_n2": _number(columns["sf_n2"][index], f"trace {trace_id} n2"),
                "sf_n3": _number(columns["sf_n3"][index], f"trace {trace_id} n3"),
            }
        elif family == "path":
            geometry |= {"path_data": columns["path_data"][index]}
        elif family == "harmonograph":
            geometry |= {
                "harm_freq_x": _number(columns["harm_freq_x"][index], f"trace {trace_id} x frequency"),
                "harm_freq_y": _number(columns["harm_freq_y"][index], f"trace {trace_id} y frequency"),
                "harm_delta": _number(columns["harm_delta"][index], f"trace {trace_id} delta"),
                "harm_damping": _number(columns["harm_damping"][index], f"trace {trace_id} damping"),
                "harm_turns": _integer(columns["harm_turns"][index], f"trace {trace_id} turns"),
            }
        else:
            raise CastingEditorError(f"trace {trace_id} has an unknown geometry family: {family}")
        traces.append(
            {
                "id": trace_id,
                "role": columns["trace_role"][index],
                "color_flow": color_flow,
                "geometry": geometry,
                "trace": {
                    "cycles_per_second": _number(columns["cycles_per_second"][index], f"trace {trace_id} speed"),
                    "trail_fraction": _number(columns["trail_fraction"][index], f"trace {trace_id} trail"),
                    "ghost_count": _integer(columns["ghost_count"][index], f"trace {trace_id} ghosts"),
                    "ghost_spacing": _number(columns["ghost_spacing"][index], f"trace {trace_id} ghost spacing"),
                    "head_radius": _number(columns["head_radius"][index], f"trace {trace_id} head radius"),
                },
                "color": columns["color"][index],
                "depth": columns["depth"][index],
                "anchor_x": _number(columns["anchor_x"][index], f"trace {trace_id} anchor x"),
                "anchor_y": _number(columns["anchor_y"][index], f"trace {trace_id} anchor y"),
                "base_scale": _number(columns["base_scale"][index], f"trace {trace_id} scale"),
                "opacity": _number(columns["opacity"][index], f"trace {trace_id} opacity"),
                "line_width": _number(columns["line_width"][index], f"trace {trace_id} line width"),
                "rotation_degrees_per_second": _number(columns["rotation_speed"][index], f"trace {trace_id} rotation speed"),
                "hue_shift_degrees": _number(columns["hue_shift"][index], f"trace {trace_id} hue shift"),
                "blend_mode": columns["blend_mode"][index],
                "drivers": drivers,
            }
        )
    return traces


def _actor_payload(fields: Mapping[str, Sequence[str]]) -> dict[str, Any]:
    actor_id = _slug(_single(fields, "actor_edit_id"))
    name = _single(fields, "actor_name")
    if not name:
        raise CastingEditorError("actor name is required")
    return {
        "id": actor_id,
        "name": name,
        "description": _single(fields, "actor_description", default=""),
        "kind": "spirogram",
        "character": _single(fields, "actor_character"),
        "components": _trace_payloads(fields),
    }


def _actor_assignment_payloads(
    fields: Mapping[str, Sequence[str]],
) -> list[dict[str, Any]]:
    ids = [str(value).strip() for value in fields.get("assignment_id", [])]
    if not ids:
        raise CastingEditorError("a scene cast requires at least one actor")
    count = len(ids)
    names = (
        "assigned_actor",
        "direction_anchor_x",
        "direction_anchor_y",
        "direction_scale",
        "direction_opacity",
        "direction_rotation",
        "direction_hue",
        "direction_depth",
        "direction_visible",
    )
    columns = {name: _repeated(fields, name, count) for name in names}
    assignments = []
    for index, assignment_id in enumerate(ids):
        direction: dict[str, Any] = {
            "scale": _number(columns["direction_scale"][index], f"actor {assignment_id} scale"),
            "opacity": _number(columns["direction_opacity"][index], f"actor {assignment_id} opacity"),
            "rotation_offset_degrees_per_second": _number(
                columns["direction_rotation"][index],
                f"actor {assignment_id} rotation",
            ),
            "hue_shift_degrees": _number(
                columns["direction_hue"][index],
                f"actor {assignment_id} hue shift",
            ),
            "visible": columns["direction_visible"][index].casefold()
            in {"1", "true", "yes", "on"},
        }
        for field, key in (
            ("direction_anchor_x", "anchor_x"),
            ("direction_anchor_y", "anchor_y"),
        ):
            value = columns[field][index]
            if value:
                direction[key] = _number(value, f"actor {assignment_id} {key}")
        depth = columns["direction_depth"][index]
        if depth:
            direction["depth"] = depth
        assignments.append(
            {
                "id": _slug(assignment_id, fallback=f"actor-{index + 1}"),
                "actor": columns["assigned_actor"][index],
                "direction": direction,
            }
        )
    return assignments


def _materialize_actor_cast(
    visuals: dict[str, Any],
    composition: Any,
) -> dict[str, Any]:
    from mrp.video.project import ActorConfig

    actors = visuals.setdefault("actors", {})
    assignments = []
    for index, trace in enumerate(composition.traces, start=1):
        actor_id = _unique_actor_id(actors, trace.id)
        actor = _actor_from_trace(trace, actor_id)
        actor = ActorConfig.model_validate(actor)
        actors[actor.id] = actor.model_dump(mode="json", exclude_none=True)
        assignments.append(
            {
                "id": _unique_actor_id(
                    {item["id"]: item for item in assignments},
                    f"{actor.id}-appearance",
                ),
                "actor": actor.id,
                "direction": {},
            }
        )
    return {
        "casting": composition.casting.model_dump(mode="json", exclude_none=True),
        "actors": assignments,
    }


def _actor_is_cast(visuals: Mapping[str, Any], actor_id: str) -> bool:
    for field in ("section_casts", "cast_overrides"):
        for cast in (visuals.get(field) or {}).values():
            if any(item.get("actor") == actor_id for item in cast.get("actors") or []):
                return True
    return False


def _style_payload(fields: Mapping[str, Sequence[str]]) -> dict[str, Any]:
    style: dict[str, Any] = {}
    roles = [str(value).strip() for value in fields.get("style_visible_roles", [])]
    if roles:
        style["visible_roles"] = roles
    for name in STYLE_NUMBER_FIELDS:
        value = _single(fields, f"style_{name}", default="")
        parsed = _optional_number(value, name.replace("_", " "))
        if parsed is not None:
            style[name] = parsed
    return style


def _write_yaml_atomic(path: Path, payload: dict[str, Any]) -> None:
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    try:
        temporary.write_text(
            yaml.safe_dump(payload, sort_keys=False, allow_unicode=True),
            encoding="utf-8",
        )
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def _invalidate_preflight(path: Path) -> None:
    if not path.is_file():
        return
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        value = {"version": 1}
    value["status"] = "stale"
    value["stale_reason"] = "versioned casting changed; run preflight or preview"
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    try:
        temporary.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def save_track_actor(
    root: Path,
    release: dict[str, Any],
    track: dict[str, Any],
    fields: Mapping[str, Sequence[str]],
) -> str | None:
    """Save one track-level actor operation without any scene dependency."""
    from mrp.video.project import ActorConfig
    from mrp.video.track_project import TrackProjectDocument

    path = project_path(root, release, track)
    document = _load_project(path)
    payload = document.model_dump(mode="json", exclude_none=True)
    visuals = payload["project"]["visuals"]
    actors = visuals.setdefault("actors", {})
    action = _single(fields, "action")
    selected_actor_id: str | None = None
    library_actor = None

    if action in {"actor_save", "actor_publish"}:
        actor_payload = _actor_payload(fields)
        original_id = _single(fields, "actor_original_id", default="")
        if original_id and original_id != actor_payload["id"]:
            raise CastingEditorError(
                "a saved actor id cannot be renamed; duplicate it instead"
            )
        existing_actor = actors.get(actor_payload["id"])
        if existing_actor and existing_actor.get("library_source"):
            actor_payload["library_source"] = existing_actor["library_source"]
        try:
            actor = ActorConfig.model_validate(actor_payload)
        except ValidationError as exc:
            raise CastingEditorError(*_validation_problems(exc)) from exc
        actors[actor.id] = actor.model_dump(mode="json", exclude_none=True)
        selected_actor_id = actor.id
        if action == "actor_publish":
            library_actor = actor
    elif action == "actor_duplicate":
        source_id = _single(fields, "actor_original_id")
        source = document.project.visuals.actors.get(source_id)
        if source is None:
            raise CastingEditorError(f"actor does not exist: {source_id}")
        duplicate_id = _unique_actor_id(actors, f"{source.id}-copy")
        duplicate = ActorConfig.model_validate(
            source.model_dump(mode="json", exclude={"library_source"})
            | {"id": duplicate_id, "name": f"{source.name} Copy"}
        )
        actors[duplicate.id] = duplicate.model_dump(mode="json", exclude_none=True)
        selected_actor_id = duplicate.id
    elif action == "actor_delete":
        actor_id = _single(fields, "actor_original_id")
        if _actor_is_cast(visuals, actor_id):
            raise CastingEditorError(
                "remove this actor from every scene cast before deleting it"
            )
        if actors.pop(actor_id, None) is None:
            raise CastingEditorError(f"actor does not exist: {actor_id}")
    elif action == "actor_import":
        library_id = _single(fields, "library_actor_id")
        library_entry = next(
            (entry for entry in _library_actors(root) if entry["id"] == library_id),
            None,
        )
        if library_entry is None:
            raise CastingEditorError(f"library actor does not exist: {library_id}")
        imported_payload = library_entry["actor"].model_dump(
            mode="json",
            exclude_none=True,
        )
        imported_payload["character"] = _single(
            fields,
            "actor_character",
            default=library_entry["actor"].components[0].role,
        )
        imported_payload["library_source"] = {
            "actor_id": library_entry["id"],
            "revision": library_entry["revision"],
        }
        imported = ActorConfig.model_validate(imported_payload)
        actors[imported.id] = imported.model_dump(mode="json", exclude_none=True)
        selected_actor_id = imported.id
    else:
        raise CastingEditorError(f"unsupported actor action: {action}")

    try:
        updated = TrackProjectDocument.model_validate(payload)
    except ValidationError as exc:
        raise CastingEditorError(*_validation_problems(exc)) from exc
    _write_yaml_atomic(path, updated.model_dump(mode="json", exclude_none=True))
    if library_actor is not None:
        _write_library_actor(root, library_actor)
    _invalidate_preflight(_preflight_path(root, release, track))
    return selected_actor_id


def save_casting(
    root: Path,
    release: dict[str, Any],
    track: dict[str, Any],
    fields: Mapping[str, Sequence[str]],
) -> dict[str, Any]:
    """Validate and atomically replace one track's versioned casting project."""
    from mrp.video.casting import generate_auto_composition
    from mrp.video.track_project import TrackProjectDocument

    path = project_path(root, release, track)
    document = _load_project(path)
    lyrics = _load_lyrics(aligned_path(root, release, track))
    section_id = _single(fields, "section_id")
    section_type = _single(fields, "section_type")
    section = next((item for item in lyrics.sections if item.id == section_id), None)
    if section is None or section.type != section_type:
        raise CastingEditorError("section identity changed while saving")
    scope = _single(fields, "scope")
    if scope not in {"type", "section"}:
        raise CastingEditorError("casting scope must be type or section")
    action = _single(fields, "action", default="save_cast")
    supported_actions = {
        "save",
        "auto",
        "clear",
        "save_cast",
        "recommended",
        "adopt",
    }
    if action not in supported_actions:
        raise CastingEditorError(f"unsupported casting action: {action}")

    payload = document.model_dump(mode="json", exclude_none=True)
    visuals = payload["project"]["visuals"]
    mapping_preset = _single(
        fields,
        "mapping_preset",
        default=document.project.visuals.mapping_preset,
    )
    palette_preset = _single(
        fields,
        "palette_preset",
        default=document.project.visuals.palette_preset,
    )
    auto_casting = _single(
        fields,
        "auto_casting",
        default="true" if document.project.visuals.auto_casting else "false",
    )
    visuals["mapping_preset"] = mapping_preset
    visuals["palette_preset"] = palette_preset
    visuals["auto_casting"] = auto_casting.casefold() in {"1", "true", "yes", "on"}

    composition_field = "section_compositions" if scope == "type" else "composition_overrides"
    actor_cast_field = "section_casts" if scope == "type" else "cast_overrides"
    style_field = "section_styles" if scope == "type" else "section_overrides"
    target = section.type if scope == "type" else section.id
    compositions = visuals.setdefault(composition_field, {})
    actor_casts = visuals.setdefault(actor_cast_field, {})
    styles = visuals.setdefault(style_field, {})
    existing = _casefold_item(compositions, target) if scope == "type" else None
    existing_key = existing[0] if existing is not None else target
    existing_actor_cast = _casefold_item(actor_casts, target) if scope == "type" else None
    existing_actor_cast_key = (
        existing_actor_cast[0] if existing_actor_cast is not None else target
    )
    existing_style = _casefold_item(styles, target) if scope == "type" else None
    existing_style_key = existing_style[0] if existing_style is not None else target
    if action in {"recommended", "adopt"}:
        composition = (
            generate_auto_composition(section.type, document.project.video.seed)
            if action == "recommended"
            else _selected_composition(document.project, section, scope)[0]
        )
        actor_casts.pop(existing_actor_cast_key, None)
        actor_casts[target] = _materialize_actor_cast(visuals, composition)
    elif action == "save_cast":
        actor_casts.pop(existing_actor_cast_key, None)
        actor_casts[target] = {
            "casting": {
                "source": "manual",
                "seed": document.project.video.seed,
                "generator_version": 1,
            },
            "actors": _actor_assignment_payloads(fields),
        }
        style = _style_payload(fields)
        styles.pop(existing_style_key, None)
        if style:
            styles[target] = style
    elif action == "clear":
        actor_casts.pop(existing_actor_cast_key, None)
        compositions.pop(existing_key, None)
        styles.pop(existing_style_key, None)
    else:
        if action == "auto":
            composition = generate_auto_composition(
                section.type,
                document.project.video.seed,
            ).model_dump(mode="json", exclude_none=True)
        else:
            composition = {
                "casting": {
                    "source": "manual",
                    "seed": document.project.video.seed,
                    "generator_version": 1,
                },
                "traces": _trace_payloads(fields),
            }
        compositions.pop(existing_key, None)
        compositions[target] = composition
        if action == "save":
            style = _style_payload(fields)
            styles.pop(existing_style_key, None)
            if style:
                styles[target] = style

    try:
        updated = TrackProjectDocument.model_validate(payload)
    except ValidationError as exc:
        raise CastingEditorError(*_validation_problems(exc)) from exc
    _write_yaml_atomic(
        path,
        updated.model_dump(mode="json", exclude_none=True),
    )
    _invalidate_preflight(_preflight_path(root, release, track))
    return load_casting(
        root,
        release,
        track,
        section_id=section.id,
        scope=scope,
    )
