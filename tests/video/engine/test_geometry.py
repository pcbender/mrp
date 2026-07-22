import json
from pathlib import Path
from typing import Any

import pytest

from mrp.video.geometry import (
    SpiroGeometry,
    generate_spiro_points,
    greatest_common_divisor,
)

FIXTURE_PATH = Path(__file__).parents[1] / "fixtures" / "trochoid-golden.json"


def test_greatest_common_divisor_matches_prototype_behavior() -> None:
    assert greatest_common_divisor(180, 65) == 5
    assert greatest_common_divisor(-12, 8) == 4
    assert greatest_common_divisor(0, 0) == 1
    assert greatest_common_divisor(12.6, 4.5) == 1


def test_python_geometry_matches_typescript_golden_fixtures() -> None:
    fixture: dict[str, Any] = json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))

    assert fixture["version"] == 1
    assert fixture["source"] == "src/core/trochoid.ts"

    for case in fixture["cases"]:
        source = case["geometry"]
        geometry = SpiroGeometry(
            fixed_radius=source["fixedRadius"],
            moving_radius=source["movingRadius"],
            pen_offset=source["penOffset"],
            phase=source["phase"],
            rotation=source["rotation"],
            samples=source["samples"],
        )
        actual = generate_spiro_points(geometry)

        assert len(actual) == len(case["points"]), case["name"]
        for point, expected in zip(actual, case["points"], strict=True):
            assert point.t == pytest.approx(expected["t"], abs=1e-12)
            assert point.x == pytest.approx(expected["x"], abs=1e-9)
            assert point.y == pytest.approx(expected["y"], abs=1e-9)
            assert point.radius == pytest.approx(expected["radius"], abs=1e-9)
            assert point.angle == pytest.approx(expected["angle"], abs=1e-12)


def test_hue_flow_values_match_prototype_semantics() -> None:
    from mrp.video.geometry import SpiroGeometry, generate_spiro_points, hue_flow_values

    points = generate_spiro_points(
        SpiroGeometry(fixed_radius=120, moving_radius=45, pen_offset=60, samples=240)
    )

    for source in ("angle", "radius", "velocity", "curvature"):
        values = hue_flow_values(points, source)
        assert len(values) == len(points)
        assert all(0 <= value <= 1 for value in values)

    # Min-max sources span the full range; curvature ends are defined as flat.
    radius_values = hue_flow_values(points, "radius")
    assert min(radius_values) == 0
    assert max(radius_values) == 1
    curvature_values = hue_flow_values(points, "curvature")
    assert curvature_values[0] == 0
    assert curvature_values[-1] == 0

    # A circle (no pen offset) has constant radius: values collapse to center.
    circle = generate_spiro_points(
        SpiroGeometry(fixed_radius=120, moving_radius=60, pen_offset=0, samples=120)
    )
    assert set(hue_flow_values(circle, "radius")) == {0.5}


def test_curve_families_close_and_sample_uniformly() -> None:
    import math

    from mrp.video.geometry import SpiroGeometry, generate_spiro_points

    cases = {
        "lissajous": SpiroGeometry(family="lissajous", liss_freq_x=3, liss_freq_y=2, samples=601),
        "rose": SpiroGeometry(family="rose", rose_n=5, rose_d=1, samples=601),
        "rose-even": SpiroGeometry(family="rose", rose_n=2, rose_d=1, samples=601),
        "superformula": SpiroGeometry(family="superformula", sf_m=6, samples=601),
        "superformula-odd": SpiroGeometry(family="superformula", sf_m=7, samples=601),
    }
    for label, geometry in cases.items():
        points = generate_spiro_points(geometry)
        assert len(points) == 601, label
        first, last = points[0], points[-1]
        assert math.hypot(first.x - last.x, first.y - last.y) < 1e-9, label


def test_lissajous_equal_frequencies_with_quarter_delta_is_a_circle() -> None:
    from mrp.video.geometry import SpiroGeometry, generate_spiro_points

    points = generate_spiro_points(
        SpiroGeometry(family="lissajous", liss_freq_x=4, liss_freq_y=4, samples=241)
    )
    radii = [point.radius for point in points]
    assert max(radii) - min(radii) < 1e-9


def test_rose_petal_counts_follow_parity() -> None:
    from mrp.video.geometry import SpiroGeometry, generate_spiro_points

    def petals(n: int, d: int) -> int:
        # phase shifts the start off a petal tip so every tip is an interior
        # maximum for the counter below.
        points = generate_spiro_points(
            SpiroGeometry(family="rose", rose_n=n, rose_d=d, samples=4801, phase=0.1)
        )
        radii = [point.radius for point in points]
        count = 0
        for index in range(1, len(radii) - 1):
            if radii[index] > 0.999 and radii[index] >= radii[index - 1] and radii[index] > radii[index + 1]:
                count += 1
        return count

    assert petals(5, 1) == 5   # odd n*d: closes at pi, n petals
    assert petals(2, 1) == 4   # even n*d: closes at 2*pi, 2n petals


def test_superformula_is_circle_at_m_zero_and_stays_finite_at_extremes() -> None:
    import math

    from mrp.video.geometry import SpiroGeometry, generate_spiro_points

    circle = generate_spiro_points(
        SpiroGeometry(family="superformula", sf_m=0, samples=121)
    )
    radii = [point.radius for point in circle]
    assert max(radii) - min(radii) < 1e-9

    extreme = generate_spiro_points(
        SpiroGeometry(family="superformula", sf_m=24, sf_n1=0.1, sf_n2=40, sf_n3=40, samples=241)
    )
    assert all(math.isfinite(point.x) and math.isfinite(point.y) for point in extreme)
