import json
from pathlib import Path

import numpy as np
import pytest
import soundfile as sf
import yaml
from typer.testing import CliRunner

from mrp.video.analysis import (
    ANALYSIS_FEATURES,
    analyze_project,
    analyze_signal,
    robust_normalize,
    smooth_attack_release,
)
from mrp.video.cli import app
from mrp.video.project import AnalysisConfig

runner = CliRunner()


def _analysis_config() -> AnalysisConfig:
    return AnalysisConfig(
        sample_rate=8000,
        frame_length=512,
        hop_length=128,
        low_cutoff_hz=200,
        high_cutoff_hz=1500,
        percentile_low=5,
        percentile_high=95,
        attack_seconds=0.02,
        release_seconds=0.1,
        vocal_activity_threshold=0.15,
    )


def _pulse_signal(sample_rate: int, duration: float) -> np.ndarray:
    times = np.arange(round(sample_rate * duration)) / sample_rate
    signal = 0.15 * np.sin(2 * np.pi * 110 * times)
    pulse_length = max(8, sample_rate // 100)
    pulse = np.hanning(pulse_length)
    for start in np.arange(0, duration, 0.5):
        index = round(start * sample_rate)
        end = min(index + pulse_length, len(signal))
        signal[index:end] += pulse[: end - index]
    return np.asarray(np.clip(signal, -1, 1), dtype=np.float32)


def _write_analysis_project(root: Path) -> Path:
    project = {
        "version": 1,
        "title": "Analysis Fixture",
        "audio": {
            "master": "audio/master.wav",
            "stems": {"vocals": "audio/vocals.wav"},
        },
        "lyrics": {"source": "lyrics.yaml", "language": "en"},
        "cards": {
            "opening": {"file": "cards/opening.jpg", "duration": 1},
            "closing": {"file": "cards/closing.jpg", "duration": 1},
        },
        "video": {"width": 1920, "height": 1080, "fps": 30},
        "text": {"font": "assets/font.ttf"},
        "analysis": {
            "sample_rate": 8000,
            "frame_length": 512,
            "hop_length": 128,
            "low_cutoff_hz": 200,
            "high_cutoff_hz": 1500,
            "attack_seconds": 0.02,
            "release_seconds": 0.1,
            "cache_dir": "build/test-analysis",
        },
    }
    for relative in ("cards/opening.jpg", "cards/closing.jpg", "assets/font.ttf"):
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"fixture")
    (root / "lyrics.yaml").write_text(
        yaml.safe_dump(
            {
                "version": 1,
                "sections": [
                    {
                        "id": "verse_1",
                        "type": "verse",
                        "lines": [{"text": "A generated fixture"}],
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    audio_dir = root / "audio"
    audio_dir.mkdir()
    sf.write(audio_dir / "master.wav", _pulse_signal(8000, 2), 8000)
    sf.write(audio_dir / "vocals.wav", _pulse_signal(16000, 2), 16000)
    manifest = root / "project.yaml"
    manifest.write_text(yaml.safe_dump(project, sort_keys=False), encoding="utf-8")
    return manifest


def test_robust_normalization_and_smoothing_are_bounded() -> None:
    normalized = robust_normalize(np.array([0, 1, 2, 3, 100]), 0, 80)
    smoothed = smooth_attack_release(
        normalized,
        frame_seconds=0.1,
        attack_seconds=0.05,
        release_seconds=0.5,
    )

    assert np.all(normalized >= 0)
    assert np.all(normalized <= 1)
    assert np.all(smoothed >= 0)
    assert np.all(smoothed <= 1)
    assert smoothed[-1] > smoothed[-2]


def test_signal_analysis_produces_shared_normalized_features() -> None:
    config = _analysis_config()
    timeline = analyze_signal(_pulse_signal(config.sample_rate, 3), config)

    assert set(timeline.features) == set(ANALYSIS_FEATURES)
    assert timeline.frame_count > 100
    assert timeline.tempo_bpm == pytest.approx(120, rel=0.2)
    for values in timeline.features.values():
        assert len(values) == timeline.frame_count
        assert np.all(values >= 0)
        assert np.all(values <= 1)

    sampled = timeline.sample(1.25)
    assert set(sampled) == set(ANALYSIS_FEATURES)
    assert all(0 <= value <= 1 for value in sampled.values())


def test_project_analysis_caches_and_reports_semantic_fallbacks(tmp_path: Path) -> None:
    manifest = _write_analysis_project(tmp_path)

    first = analyze_project(manifest)
    second = analyze_project(manifest)

    assert not first.cache_hit
    assert second.cache_hit
    assert first.cache_path.is_file()
    assert list(first.bundle.tracks) == ["master", "vocals"]
    assert first.bundle.tracks["master"].frame_count == first.bundle.tracks[
        "vocals"
    ].frame_count
    np.testing.assert_array_equal(
        first.bundle.tracks["master"].times,
        first.bundle.tracks["vocals"].times,
    )
    assert first.bundle.semantic_controls["vocals"].track == "vocals"
    assert first.bundle.semantic_controls["drums"].track == "master"
    assert first.bundle.semantic_controls["drums"].energy_feature == "high_energy"
    assert any("drums" in warning for warning in first.warnings)

    result = runner.invoke(app, ["analyze", str(manifest), "--json"])
    assert result.exit_code == 0, result.output
    summary = json.loads(result.stdout)
    assert summary["cache_hit"] is True
    assert summary["tracks"]["master"]["frames"] > 0

    sf.write(
        tmp_path / "audio" / "master.wav",
        _pulse_signal(8000, 2) * 0.5,
        8000,
    )
    changed = analyze_project(manifest)
    assert not changed.cache_hit
    assert changed.cache_path != first.cache_path


def test_analysis_configuration_rejects_invalid_frequency_bands() -> None:
    with pytest.raises(ValueError, match="Nyquist"):
        AnalysisConfig(sample_rate=8000, high_cutoff_hz=4000)


def test_silent_audio_produces_finite_zero_controls() -> None:
    config = _analysis_config()
    timeline = analyze_signal(
        np.zeros(config.frame_length * 2, dtype=np.float32),
        config,
    )

    assert timeline.tempo_bpm == 0
    assert timeline.beat_times.size == 0
    for values in timeline.features.values():
        assert np.all(np.isfinite(values))
        assert np.all(values == 0)
