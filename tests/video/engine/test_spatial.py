import math

import numpy as np
import pytest

from mrp.video.spatial import (
    lift_curve_points,
    project_curve_points,
    spatial_orientations,
)


def test_wave_lift_uses_closed_whole_windings() -> None:
    points = np.asarray(((1, 0), (0, 1), (1, 0)), dtype=np.float32)
    progress = np.asarray((0, 0.25, 1), dtype=np.float32)

    lifted = lift_curve_points(
        points,
        progress,
        mode="wave",
        amplitude=0.5,
        windings=1,
        phase_degrees=0,
    )

    np.testing.assert_allclose(lifted[:, :2], points)
    np.testing.assert_allclose(lifted[:, 2], (0, 0.5, 0), atol=1e-6)
    np.testing.assert_allclose(lifted[0], lifted[-1], atol=1e-6)
    assert not lifted.flags.writeable


def test_tilted_lift_is_planar() -> None:
    points = np.asarray(((0, 0), (1, -1)), dtype=np.float32)
    lifted = lift_curve_points(
        points,
        np.asarray((0, 1), dtype=np.float32),
        mode="tilted",
        amplitude=1,
        windings=24,
        phase_degrees=270,
    )

    np.testing.assert_array_equal(lifted[:, 2], (0, 0))


def test_projection_rotates_then_applies_bounded_perspective_and_depth() -> None:
    projected, depth = project_curve_points(
        np.asarray(((0.3, -0.4, 0.5),), dtype=np.float32),
        pitch_radians=0.2,
        yaw_radians=-0.3,
        roll_radians=0.4,
        perspective_strength=0.18,
    )

    # These values are also asserted by the browser preview test, guarding the
    # shared Python/JavaScript camera convention.
    np.testing.assert_allclose(
        projected[0],
        (0.3761265277862549, -0.42500215768814087),
        atol=1e-7,
    )
    assert depth[0] == pytest.approx(0.6700183153152466, abs=1e-7)
    assert 0 <= depth[0] <= 1
    assert np.isfinite(projected).all()


def test_yaw_places_positive_x_farther_from_camera() -> None:
    projected, depth = project_curve_points(
        np.asarray(((1, 0, 0), (0, 0, 1)), dtype=np.float32),
        pitch_radians=0,
        yaw_radians=math.pi / 2,
        roll_radians=0,
        perspective_strength=0.2,
    )

    np.testing.assert_allclose(projected[0], (0, 0), atol=1e-7)
    np.testing.assert_allclose(projected[1], (1, 0), atol=1e-7)
    assert depth[0] < 0.5
    assert depth[1] == pytest.approx(0.5)


def test_circuit_step_holds_then_retains_completed_orientations() -> None:
    before, before_history = spatial_orientations(
        base_pitch_degrees=0,
        base_yaw_degrees=0,
        pitch_degrees_per_second=0,
        yaw_degrees_per_second=0,
        motion_time=100,
        trace_time=1.999,
        cycles_per_second=0.5,
        orientation_mode="circuit_step",
        pitch_step_degrees=0,
        yaw_step_degrees=15,
        retained_circuits=2,
        retention_fade=0.5,
    )
    boundary, boundary_history = spatial_orientations(
        base_pitch_degrees=0,
        base_yaw_degrees=0,
        pitch_degrees_per_second=0,
        yaw_degrees_per_second=0,
        motion_time=100,
        trace_time=2,
        cycles_per_second=0.5,
        orientation_mode="circuit_step",
        pitch_step_degrees=0,
        yaw_step_degrees=15,
        retained_circuits=2,
        retention_fade=0.5,
    )
    third, third_history = spatial_orientations(
        base_pitch_degrees=0,
        base_yaw_degrees=0,
        pitch_degrees_per_second=0,
        yaw_degrees_per_second=0,
        motion_time=100,
        trace_time=6.1,
        cycles_per_second=0.5,
        orientation_mode="circuit_step",
        pitch_step_degrees=0,
        yaw_step_degrees=15,
        retained_circuits=2,
        retention_fade=0.5,
    )

    assert before.yaw_radians == 0
    assert before_history == ()
    assert boundary.yaw_radians == pytest.approx(math.radians(15))
    assert [item.yaw_radians for item in boundary_history] == [0]
    assert third.yaw_radians == pytest.approx(math.radians(45))
    assert [item.yaw_radians for item in third_history] == pytest.approx(
        [math.radians(15), math.radians(30)]
    )
    assert [item.opacity for item in third_history] == pytest.approx([0.25, 0.5])
