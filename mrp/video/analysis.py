import hashlib
import json
import math
import os
import zipfile
from collections.abc import Callable, Mapping
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

import librosa
import numpy as np
import soundfile as sf
from numpy.typing import NDArray

from mrp.video.project import (
    AnalysisConfig,
    ProjectManifest,
    load_project_manifest,
    validate_project,
)

ANALYSIS_FORMAT_VERSION = 1
ANALYSIS_FEATURES = (
    "rms",
    "peak",
    "low_energy",
    "mid_energy",
    "high_energy",
    "spectral_centroid",
    "spectral_flux",
    "onset_strength",
    "vocal_activity",
)
ProgressCallback = Callable[[str], None]


@dataclass(frozen=True, slots=True)
class FeatureTimeline:
    times: NDArray[np.float64]
    features: dict[str, NDArray[np.float32]]
    tempo_bpm: float
    beat_times: NDArray[np.float64]

    @property
    def frame_count(self) -> int:
        return len(self.times)

    def sample(self, time_seconds: float) -> dict[str, float]:
        """Interpolate every feature on the shared musical timeline."""
        if not self.frame_count:
            return {name: 0.0 for name in self.features}
        return {
            name: float(
                np.interp(
                    time_seconds,
                    self.times,
                    values,
                    left=values[0],
                    right=values[-1],
                )
            )
            for name, values in self.features.items()
        }


@dataclass(frozen=True, slots=True)
class SemanticControl:
    track: str
    energy_feature: str
    accent_feature: str


@dataclass(frozen=True, slots=True)
class AnalysisBundle:
    cache_key: str
    duration: float
    sample_rate: int
    frame_length: int
    hop_length: int
    input_hashes: dict[str, str]
    tracks: dict[str, FeatureTimeline]
    semantic_controls: dict[str, SemanticControl]


@dataclass(frozen=True, slots=True)
class AnalysisRun:
    bundle: AnalysisBundle
    cache_path: Path
    cache_hit: bool
    warnings: tuple[str, ...]

    def summary(self) -> dict[str, Any]:
        return {
            "cache_key": self.bundle.cache_key,
            "cache_path": str(self.cache_path),
            "cache_hit": self.cache_hit,
            "duration": self.bundle.duration,
            "sample_rate": self.bundle.sample_rate,
            "frame_length": self.bundle.frame_length,
            "hop_length": self.bundle.hop_length,
            "tracks": {
                name: {
                    "frames": timeline.frame_count,
                    "tempo_bpm": timeline.tempo_bpm,
                    "beats": len(timeline.beat_times),
                }
                for name, timeline in self.bundle.tracks.items()
            },
            "semantic_controls": {
                role: asdict(control)
                for role, control in self.bundle.semantic_controls.items()
            },
            "warnings": list(self.warnings),
        }


class SpirophonicAnalysisError(Exception):
    pass


def robust_normalize(
    values: NDArray[np.floating[Any]],
    percentile_low: float,
    percentile_high: float,
) -> NDArray[np.float32]:
    """Normalize a feature with robust per-track percentile bounds."""
    clean = np.nan_to_num(
        np.asarray(values, dtype=np.float64),
        nan=0.0,
        posinf=0.0,
        neginf=0.0,
    )
    if clean.size == 0:
        return np.asarray(clean, dtype=np.float32)

    low, high = np.percentile(clean, [percentile_low, percentile_high])
    span = float(high - low)
    if span <= np.finfo(np.float64).eps:
        return np.zeros_like(clean, dtype=np.float32)
    return np.asarray(np.clip((clean - low) / span, 0, 1), dtype=np.float32)


def smooth_attack_release(
    values: NDArray[np.floating[Any]],
    *,
    frame_seconds: float,
    attack_seconds: float,
    release_seconds: float,
) -> NDArray[np.float32]:
    """Apply deterministic one-pole smoothing with separate rise/fall timing."""
    source = np.asarray(values, dtype=np.float64)
    if source.size == 0:
        return np.asarray(source, dtype=np.float32)

    attack_alpha = 1 - math.exp(-frame_seconds / attack_seconds)
    release_alpha = 1 - math.exp(-frame_seconds / release_seconds)
    smoothed = np.empty_like(source)
    smoothed[0] = source[0]
    for index in range(1, len(source)):
        alpha = attack_alpha if source[index] > smoothed[index - 1] else release_alpha
        smoothed[index] = smoothed[index - 1] + alpha * (
            source[index] - smoothed[index - 1]
        )
    return np.asarray(smoothed, dtype=np.float32)


def _fit_feature(values: NDArray[Any], frame_count: int) -> NDArray[np.float64]:
    source = np.ravel(np.asarray(values, dtype=np.float64))
    if len(source) == frame_count:
        return source
    if not len(source):
        return np.zeros(frame_count, dtype=np.float64)
    if len(source) > frame_count:
        return source[:frame_count]
    return np.pad(source, (0, frame_count - len(source)), mode="edge")


def _band_energy(
    magnitude: NDArray[np.float64],
    frequencies: NDArray[np.float64],
    lower: float,
    upper: float | None,
) -> NDArray[np.float64]:
    mask = frequencies >= lower
    if upper is not None:
        mask &= frequencies < upper
    if not np.any(mask):
        return np.zeros(magnitude.shape[1], dtype=np.float64)
    return np.sqrt(np.mean(np.square(magnitude[mask]), axis=0))


def analyze_signal(
    signal: NDArray[np.floating[Any]],
    config: AnalysisConfig,
) -> FeatureTimeline:
    """Extract normalized, smoothed features from one mono analysis signal."""
    samples = np.nan_to_num(np.asarray(signal, dtype=np.float32))
    if len(samples) < config.frame_length:
        samples = np.pad(samples, (0, config.frame_length - len(samples)))

    frames = librosa.util.frame(
        samples,
        frame_length=config.frame_length,
        hop_length=config.hop_length,
    )
    rms = np.sqrt(np.mean(np.square(frames, dtype=np.float64), axis=0))
    peak = np.max(np.abs(frames), axis=0)
    magnitude = np.abs(
        librosa.stft(
            samples,
            n_fft=config.frame_length,
            hop_length=config.hop_length,
            win_length=config.frame_length,
            center=False,
        )
    ).astype(np.float64)
    frame_count = magnitude.shape[1]
    frequencies = librosa.fft_frequencies(
        sr=config.sample_rate,
        n_fft=config.frame_length,
    )
    magnitude_sum = np.sum(magnitude, axis=0)
    centroid = np.divide(
        np.sum(frequencies[:, np.newaxis] * magnitude, axis=0),
        magnitude_sum,
        out=np.zeros(frame_count, dtype=np.float64),
        where=magnitude_sum > 0,
    )
    spectral_profile = np.divide(
        magnitude,
        magnitude_sum,
        out=np.zeros_like(magnitude),
        where=magnitude_sum > 0,
    )
    positive_delta = np.maximum(
        np.diff(spectral_profile, axis=1, prepend=spectral_profile[:, :1]),
        0,
    )
    spectral_flux = np.sqrt(np.sum(np.square(positive_delta), axis=0))

    if np.max(magnitude, initial=0) > 0:
        onset_db = librosa.amplitude_to_db(magnitude, ref=np.max)
        onset_strength = librosa.onset.onset_strength(
            S=onset_db,
            sr=config.sample_rate,
            hop_length=config.hop_length,
            center=False,
            aggregate=np.mean,
        )
    else:
        onset_strength = np.zeros(frame_count, dtype=np.float64)
    onset_strength = _fit_feature(onset_strength, frame_count)

    raw_features = {
        "rms": _fit_feature(rms, frame_count),
        "peak": _fit_feature(peak, frame_count),
        "low_energy": _band_energy(
            magnitude,
            frequencies,
            0,
            config.low_cutoff_hz,
        ),
        "mid_energy": _band_energy(
            magnitude,
            frequencies,
            config.low_cutoff_hz,
            config.high_cutoff_hz,
        ),
        "high_energy": _band_energy(
            magnitude,
            frequencies,
            config.high_cutoff_hz,
            None,
        ),
        "spectral_centroid": centroid,
        "spectral_flux": spectral_flux,
        "onset_strength": onset_strength,
    }
    frame_seconds = config.hop_length / config.sample_rate
    features = {
        name: smooth_attack_release(
            robust_normalize(
                values,
                config.percentile_low,
                config.percentile_high,
            ),
            frame_seconds=frame_seconds,
            attack_seconds=config.attack_seconds,
            release_seconds=config.release_seconds,
        )
        for name, values in raw_features.items()
    }
    activity = np.asarray(
        features["rms"] >= config.vocal_activity_threshold,
        dtype=np.float32,
    )
    features["vocal_activity"] = smooth_attack_release(
        activity,
        frame_seconds=frame_seconds,
        attack_seconds=config.attack_seconds,
        release_seconds=config.release_seconds,
    )

    tempo_bpm = 0.0
    beat_frames = np.array([], dtype=np.int64)
    if np.max(onset_strength, initial=0) > 0:
        tempo, beat_frames = librosa.beat.beat_track(
            onset_envelope=onset_strength,
            sr=config.sample_rate,
            hop_length=config.hop_length,
        )
        tempo_values = np.ravel(np.asarray(tempo, dtype=np.float64))
        if tempo_values.size and math.isfinite(tempo_values[0]):
            tempo_bpm = float(tempo_values[0])

    frame_centers = (
        np.arange(frame_count, dtype=np.float64) * config.hop_length
        + config.frame_length / 2
    )
    times = frame_centers / config.sample_rate
    beat_times = (
        np.asarray(beat_frames, dtype=np.float64) * config.hop_length
        + config.frame_length / 2
    ) / config.sample_rate
    return FeatureTimeline(
        times=times,
        features=features,
        tempo_bpm=tempo_bpm,
        beat_times=beat_times,
    )


def _decode_audio(path: Path, sample_rate: int) -> NDArray[np.float32]:
    try:
        audio, original_rate = sf.read(path, dtype="float32", always_2d=True)
    except (OSError, RuntimeError, ValueError) as exc:
        message = f"cannot decode audio file {path}: {exc}"
        raise SpirophonicAnalysisError(message) from exc
    if not len(audio):
        raise SpirophonicAnalysisError(f"audio file is empty: {path}")
    mono = np.mean(audio, axis=1, dtype=np.float64).astype(np.float32)
    if original_rate != sample_rate:
        mono = librosa.resample(
            mono,
            orig_sr=original_rate,
            target_sr=sample_rate,
        ).astype(np.float32)
    return mono


def _match_master_length(
    signal: NDArray[np.float32],
    master_length: int,
) -> NDArray[np.float32]:
    if len(signal) >= master_length:
        return np.asarray(signal[:master_length], dtype=np.float32)
    return np.pad(signal, (0, master_length - len(signal))).astype(np.float32)


def _semantic_controls(track_names: set[str]) -> tuple[
    dict[str, SemanticControl],
    tuple[str, ...],
]:
    controls = {
        "master": SemanticControl("master", "rms", "onset_strength"),
        "drums": SemanticControl(
            "drums" if "drums" in track_names else "master",
            "rms" if "drums" in track_names else "high_energy",
            "onset_strength",
        ),
        "bass": SemanticControl(
            "bass" if "bass" in track_names else "master",
            "rms" if "bass" in track_names else "low_energy",
            "spectral_flux",
        ),
        "vocals": SemanticControl(
            "vocals" if "vocals" in track_names else "master",
            "rms" if "vocals" in track_names else "mid_energy",
            "vocal_activity",
        ),
        "instruments": SemanticControl(
            "instruments" if "instruments" in track_names else "master",
            "rms" if "instruments" in track_names else "mid_energy",
            "spectral_flux",
        ),
    }
    semantic_roles = ("drums", "bass", "vocals", "instruments")
    missing = [role for role in semantic_roles if role not in track_names]
    warnings = tuple(
        f"optional '{role}' stem is missing; using master-derived features"
        for role in missing
    )
    return controls, warnings


def _hash_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _analysis_key(
    project: ProjectManifest,
    input_hashes: Mapping[str, str],
) -> str:
    versions = {
        "analysis_format": ANALYSIS_FORMAT_VERSION,
        "librosa": librosa.__version__,
        "numpy": np.__version__,
        "soundfile": sf.__version__,
    }
    settings = project.analysis.model_dump(mode="json", exclude={"cache_dir"})
    payload = json.dumps(
        {
            "versions": versions,
            "settings": settings,
            "inputs": dict(sorted(input_hashes.items())),
        },
        sort_keys=True,
        separators=(",", ":"),
    ).encode()
    return hashlib.sha256(payload).hexdigest()


def _write_cache(path: Path, bundle: AnalysisBundle) -> None:
    metadata = {
        "format_version": ANALYSIS_FORMAT_VERSION,
        "cache_key": bundle.cache_key,
        "duration": bundle.duration,
        "sample_rate": bundle.sample_rate,
        "frame_length": bundle.frame_length,
        "hop_length": bundle.hop_length,
        "input_hashes": bundle.input_hashes,
        "tracks": list(bundle.tracks),
        "features": list(ANALYSIS_FEATURES),
        "semantic_controls": {
            role: asdict(control) for role, control in bundle.semantic_controls.items()
        },
    }
    arrays: dict[str, NDArray[Any]] = {
        "metadata": np.asarray(json.dumps(metadata, sort_keys=True))
    }
    for index, timeline in enumerate(bundle.tracks.values()):
        arrays[f"track_{index}_times"] = timeline.times
        arrays[f"track_{index}_beat_times"] = timeline.beat_times
        arrays[f"track_{index}_tempo"] = np.asarray(timeline.tempo_bpm)
        for feature_name in ANALYSIS_FEATURES:
            arrays[f"track_{index}_{feature_name}"] = timeline.features[feature_name]

    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    try:
        with temporary.open("wb") as stream:
            np.savez_compressed(stream, **arrays)
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def _load_cache(path: Path, expected_key: str) -> AnalysisBundle:
    try:
        with np.load(path, allow_pickle=False) as archive:
            metadata = json.loads(str(archive["metadata"].item()))
            if metadata["format_version"] != ANALYSIS_FORMAT_VERSION:
                raise ValueError("analysis cache format version does not match")
            if metadata["cache_key"] != expected_key:
                raise ValueError("analysis cache key does not match")
            tracks: dict[str, FeatureTimeline] = {}
            for index, name in enumerate(metadata["tracks"]):
                features = {
                    feature_name: np.asarray(
                        archive[f"track_{index}_{feature_name}"],
                        dtype=np.float32,
                    )
                    for feature_name in metadata["features"]
                }
                tracks[name] = FeatureTimeline(
                    times=np.asarray(archive[f"track_{index}_times"], dtype=np.float64),
                    features=features,
                    tempo_bpm=float(archive[f"track_{index}_tempo"].item()),
                    beat_times=np.asarray(
                        archive[f"track_{index}_beat_times"],
                        dtype=np.float64,
                    ),
                )
    except (
        OSError,
        KeyError,
        TypeError,
        ValueError,
        zipfile.BadZipFile,
        json.JSONDecodeError,
    ) as exc:
        raise SpirophonicAnalysisError(f"invalid analysis cache {path}: {exc}") from exc

    controls = {
        role: SemanticControl(**value)
        for role, value in metadata["semantic_controls"].items()
    }
    return AnalysisBundle(
        cache_key=metadata["cache_key"],
        duration=float(metadata["duration"]),
        sample_rate=int(metadata["sample_rate"]),
        frame_length=int(metadata["frame_length"]),
        hop_length=int(metadata["hop_length"]),
        input_hashes=dict(metadata["input_hashes"]),
        tracks=tracks,
        semantic_controls=controls,
    )


def _cache_metadata(path: Path) -> dict[str, Any]:
    try:
        with np.load(path, allow_pickle=False) as archive:
            value = json.loads(str(archive["metadata"].item()))
    except (
        OSError,
        KeyError,
        TypeError,
        ValueError,
        zipfile.BadZipFile,
        json.JSONDecodeError,
    ) as exc:
        raise SpirophonicAnalysisError(f"invalid analysis cache {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise SpirophonicAnalysisError(
            f"invalid analysis cache {path}: metadata must be a mapping"
        )
    return value


def load_existing_analysis(manifest_path: Path) -> AnalysisRun | None:
    """Load a current analysis cache without hashing, decoding, or writing audio.

    This is the read-only path used by interactive previews. A candidate is
    accepted only when its recorded key matches the current analysis settings
    and declared inputs, and no input has a newer modification time than the
    cache. Missing, malformed, or stale caches return ``None``; callers that
    need to create or refresh analysis must use :func:`analyze_project`.
    """
    manifest = manifest_path.expanduser().resolve()
    project = load_project_manifest(manifest)
    root = manifest.parent
    input_paths = {
        "master": (root / project.audio.master).resolve(),
        **{
            name: (root / relative_path).resolve()
            for name, relative_path in sorted(project.audio.stems.items())
        },
    }
    if any(not path.is_file() for path in input_paths.values()):
        return None

    cache_dir = (root / project.analysis.cache_dir).resolve()
    try:
        cache_dir.relative_to(root)
    except ValueError:
        return None
    if not cache_dir.is_dir():
        return None

    try:
        candidates = sorted(
            cache_dir.glob("*.npz"),
            key=lambda path: (path.stat().st_mtime_ns, path.name),
            reverse=True,
        )
    except OSError:
        return None
    semantic_controls, warnings = _semantic_controls(set(input_paths))
    for cache_path in candidates:
        try:
            metadata = _cache_metadata(cache_path)
            cache_key = str(metadata["cache_key"])
            input_hashes = {
                str(name): str(value)
                for name, value in dict(metadata["input_hashes"]).items()
            }
            if metadata.get("format_version") != ANALYSIS_FORMAT_VERSION:
                continue
            if cache_path.stem != cache_key:
                continue
            if set(input_hashes) != set(input_paths):
                continue
            if _analysis_key(project, input_hashes) != cache_key:
                continue
            cache_mtime = cache_path.stat().st_mtime_ns
            if any(path.stat().st_mtime_ns > cache_mtime for path in input_paths.values()):
                continue
            bundle = _load_cache(cache_path, cache_key)
        except (
            OSError,
            KeyError,
            TypeError,
            ValueError,
            SpirophonicAnalysisError,
        ):
            continue
        if bundle.semantic_controls != semantic_controls:
            continue
        return AnalysisRun(bundle, cache_path, True, warnings)
    return None


def analyze_project(
    manifest_path: Path,
    *,
    force: bool = False,
    validate_aligned: bool = True,
    progress: ProgressCallback | None = None,
) -> AnalysisRun:
    """Validate, analyze, cache, and return all declared project audio tracks."""
    notify = progress or (lambda _message: None)
    notify("Validating project inputs")
    report = validate_project(manifest_path, validate_aligned=validate_aligned)
    project = report.project
    root = report.manifest_path.parent
    input_paths = {
        "master": (root / project.audio.master).resolve(),
        **{
            name: (root / relative_path).resolve()
            for name, relative_path in sorted(project.audio.stems.items())
        },
    }

    notify("Hashing audio inputs")
    input_hashes = {name: _hash_file(path) for name, path in input_paths.items()}
    cache_key = _analysis_key(project, input_hashes)
    cache_path = (root / project.analysis.cache_dir / f"{cache_key}.npz").resolve()
    semantic_controls, warnings = _semantic_controls(set(input_paths))

    if cache_path.is_file() and not force:
        notify("Loading cached analysis")
        bundle = _load_cache(cache_path, cache_key)
        return AnalysisRun(bundle, cache_path, True, warnings)

    notify("Decoding master audio")
    master = _decode_audio(input_paths["master"], project.analysis.sample_rate)
    master_length = len(master)
    duration = master_length / project.analysis.sample_rate
    signals = {"master": master}
    for name, path in input_paths.items():
        if name == "master":
            continue
        notify(f"Decoding {name} stem")
        signals[name] = _match_master_length(
            _decode_audio(path, project.analysis.sample_rate),
            master_length,
        )

    tracks: dict[str, FeatureTimeline] = {}
    for name, signal in signals.items():
        notify(f"Extracting features for {name}")
        tracks[name] = analyze_signal(signal, project.analysis)

    bundle = AnalysisBundle(
        cache_key=cache_key,
        duration=duration,
        sample_rate=project.analysis.sample_rate,
        frame_length=project.analysis.frame_length,
        hop_length=project.analysis.hop_length,
        input_hashes=input_hashes,
        tracks=tracks,
        semantic_controls=semantic_controls,
    )
    notify("Writing analysis cache")
    _write_cache(cache_path, bundle)
    return AnalysisRun(bundle, cache_path, False, warnings)
