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
