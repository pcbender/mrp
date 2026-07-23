from __future__ import annotations

import math
from pathlib import Path

import numpy as np
import pytest

from mrp.video.geometry import SpiroGeometry, generate_text_points
from mrp.video.project import LayerGeometryConfig
from mrp.video.renderer import _build_curves

# Two 10x10 squares side by side: a self-contained multi-subpath "word".
TWO_SHAPES = "M 0 0 L 10 0 L 10 10 L 0 10 Z M 40 0 L 50 0 L 50 10 L 40 10 Z"


def _text_geometry(path_data: str = TWO_SHAPES, samples: int = 128) -> SpiroGeometry:
    config = LayerGeometryConfig(family="text", path_data=path_data, samples=samples)
    return SpiroGeometry(**config.model_dump(exclude_none=True))


def test_text_family_validates_multiple_subpaths() -> None:
    config = LayerGeometryConfig(family="text", path_data=TWO_SHAPES)
    assert config.family == "text"
    assert config.path_data.count("M") == 2


def test_text_family_requires_path_data() -> None:
    with pytest.raises(ValueError):
        LayerGeometryConfig(family="text")


def test_path_family_still_rejects_multiple_subpaths() -> None:
    # The single-subpath contract for `path` is unchanged.
    with pytest.raises(ValueError):
        LayerGeometryConfig(family="path", path_data=TWO_SHAPES)


def test_generate_text_points_group_normalizes_contours() -> None:
    contours = generate_text_points(_text_geometry())
    assert len(contours) == 2
    xs = np.concatenate([[p.x for p in contour] for contour in contours])
    ys = np.concatenate([[p.y for p in contour] for contour in contours])
    # Group-normalized: whole word centered, spread wider in x than y (the two
    # squares sit side by side), max radius ~1.
    assert abs((xs.max() + xs.min()) / 2) < 1e-6
    assert xs.max() - xs.min() > ys.max() - ys.min()
    assert math.isclose(float(np.max(np.hypot(xs, ys))), 1.0, rel_tol=1e-3)
    # The two contours keep their separation (left square vs right square).
    left_cx = np.mean([p.x for p in contours[0]])
    right_cx = np.mean([p.x for p in contours[1]])
    assert left_cx < right_cx


def test_build_curves_expands_text_into_one_curve_per_contour() -> None:
    layer = LayerGeometryConfig(family="text", path_data=TWO_SHAPES, samples=128)
    from mrp.video.project import VisualLayerConfig

    config = VisualLayerConfig(id="song-title", role="vocals", color="#ffcc00", geometry=layer)
    curves = _build_curves(config, seed=42, namespace="chorus")
    assert len(curves) == 2
    assert all(curve.config.id == "song-title" for curve in curves)
    # Per-contour phase offsets stagger the letter trails.
    assert len({round(curve.phase_offset, 6) for curve in curves}) == 2
    # Group scale preserved: the union max-norm is ~1, not each contour to 1.
    assert math.isclose(
        max(float(np.max(np.linalg.norm(curve.points, axis=1))) for curve in curves),
        1.0,
        rel_tol=1e-3,
    )


def test_non_text_layer_yields_single_curve() -> None:
    from mrp.video.project import VisualLayerConfig

    config = VisualLayerConfig(
        id="petal",
        role="vocals",
        color="#00ffcc",
        geometry=LayerGeometryConfig(family="rose", rose_n=5, rose_d=1),
    )
    assert len(_build_curves(config, seed=1)) == 1


def test_text_layer_renders_into_a_frame() -> None:
    """End-to-end: a text layer draws visible strokes in a rendered frame."""
    from mrp.video.project import ProjectManifest
    from mrp.video.renderer import build_render_context, render_frame
    from tests.video.engine.test_choreography import (
        _aligned_sections,
        _analysis_bundle,
    )

    font = Path("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf")
    if not font.is_file():
        pytest.skip("DejaVuSans not available")

    project = ProjectManifest.model_validate(
        {
            "version": 1,
            "title": "Text Layer Fixture",
            "audio": {"master": "master.wav"},
            "lyrics": {"source": "lyrics.yaml", "language": "en"},
            "cards": {
                "opening": {"file": "open.jpg", "duration": 1},
                "closing": {"file": "close.jpg", "duration": 1},
            },
            "video": {"width": 320, "height": 180, "fps": 10, "seed": 7},
            "text": {"font": font.name, "size": 28},
            "visuals": {
                "layers": [
                    {
                        "id": "song-title",
                        "role": "vocals",
                        "color": "#ffcc00",
                        "opacity": 1.0,
                        "line_width": 2.0,
                        "geometry": {
                            "family": "text",
                            "path_data": TWO_SHAPES,
                            "samples": 128,
                        },
                        "trace": {"cycles_per_second": 0.5, "trail_fraction": 1.0},
                    }
                ]
            },
        }
    )
    context = build_render_context(
        project, _analysis_bundle(), _aligned_sections(), root=font.parent
    )
    # Two contours from one text layer -> two curves in the global layer set.
    assert len(context.layers) == 2
    frame = render_frame(context, 4.5, 45, width=320, height=180)
    # The text layer painted something over the background.
    assert frame.std() > 0
