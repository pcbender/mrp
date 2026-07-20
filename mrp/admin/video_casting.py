"""Versioned section-casting edits for the per-track Video workspace."""
from __future__ import annotations

import json
import math
import os
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
    from mrp.video.workspace import TrackProjectDocument

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


def load_casting(
    root: Path,
    release: dict[str, Any],
    track: dict[str, Any],
    *,
    section_id: str | None = None,
    scope: str = "type",
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
                "overridden": section.id in document.project.visuals.composition_overrides,
            }
        )
    composition, composition_source = _selected_composition(
        document.project,
        selected,
        scope,
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
        "fixed_radius",
        "moving_radius",
        "pen_offset",
        "geometry_rotation",
        "samples",
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
        traces.append(
            {
                "id": trace_id,
                "role": columns["trace_role"][index],
                "geometry": {
                    "fixed_radius": _number(columns["fixed_radius"][index], f"trace {trace_id} fixed radius"),
                    "moving_radius": _number(columns["moving_radius"][index], f"trace {trace_id} moving radius"),
                    "pen_offset": _number(columns["pen_offset"][index], f"trace {trace_id} pen offset"),
                    "rotation": columns["geometry_rotation"][index],
                    "samples": _integer(columns["samples"][index], f"trace {trace_id} samples"),
                },
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


def save_casting(
    root: Path,
    release: dict[str, Any],
    track: dict[str, Any],
    fields: Mapping[str, Sequence[str]],
) -> dict[str, Any]:
    """Validate and atomically replace one track's versioned casting project."""
    from mrp.video.casting import generate_auto_composition
    from mrp.video.workspace import TrackProjectDocument

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
    action = _single(fields, "action", default="save")
    if action not in {"save", "auto", "clear"}:
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
    style_field = "section_styles" if scope == "type" else "section_overrides"
    target = section.type if scope == "type" else section.id
    compositions = visuals.setdefault(composition_field, {})
    styles = visuals.setdefault(style_field, {})
    existing = _casefold_item(compositions, target) if scope == "type" else None
    existing_key = existing[0] if existing is not None else target
    existing_style = _casefold_item(styles, target) if scope == "type" else None
    existing_style_key = existing_style[0] if existing_style is not None else target

    if action == "clear":
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
