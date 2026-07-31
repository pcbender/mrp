"""Deterministic three-dimensional lift and camera projection for curves."""

import math
from dataclasses import dataclass

import numpy as np
from numpy.typing import NDArray


@dataclass(frozen=True, slots=True)
class SpatialOrientation:
    """One projected orientation and its opacity relative to the current trace."""

    pitch_radians: float
    yaw_radians: float
    opacity: float = 1.0


def retained_spatial_orientations(
    *,
    current_pitch_radians: float,
    current_yaw_radians: float,
    trace_time: float,
    cycles_per_second: float,
    orientation_mode: str,
    pitch_step_degrees: float,
    yaw_step_degrees: float,
    retained_circuits: int,
    retention_fade: float,
) -> tuple[SpatialOrientation, ...]:
    """Return completed circuit orientations, oldest first."""
    if trace_time < 0:
        raise ValueError("trace_time must be non-negative")
    if cycles_per_second <= 0:
        raise ValueError("cycles_per_second must be positive")
    if orientation_mode not in {"continuous", "circuit_step"}:
        raise ValueError("orientation_mode must be 'continuous' or 'circuit_step'")
    if retained_circuits < 0:
        raise ValueError("retained_circuits must be non-negative")
    if not 0 <= retention_fade <= 1:
        raise ValueError("retention_fade must be between 0 and 1")
    if orientation_mode != "circuit_step":
        return ()
    completed = math.floor(trace_time * cycles_per_second + 1e-9)
    history = min(completed, retained_circuits)
    pitch_step = math.radians(pitch_step_degrees)
    yaw_step = math.radians(yaw_step_degrees)
    return tuple(
        SpatialOrientation(
            pitch_radians=current_pitch_radians - pitch_step * age,
            yaw_radians=current_yaw_radians - yaw_step * age,
            opacity=retention_fade**age,
        )
        for age in range(history, 0, -1)
        if retention_fade**age > 0
    )


def spatial_orientations(
    *,
    base_pitch_degrees: float,
    base_yaw_degrees: float,
    pitch_degrees_per_second: float,
    yaw_degrees_per_second: float,
    motion_time: float,
    trace_time: float,
    cycles_per_second: float,
    orientation_mode: str,
    pitch_step_degrees: float,
    yaw_step_degrees: float,
    retained_circuits: int,
    retention_fade: float,
) -> tuple[SpatialOrientation, tuple[SpatialOrientation, ...]]:
    """Resolve the current and retained spatial orientations.

    Continuous tumble is additive in either timing mode. Circuit-step motion
    advances only after a whole trace traversal, using the same integrated
    trace clock that positions the animated head. Retained circuits are
    returned oldest-first so painters can layer newer history over older wire.
    """
    if motion_time < 0 or trace_time < 0:
        raise ValueError("motion_time and trace_time must be non-negative")
    if cycles_per_second <= 0:
        raise ValueError("cycles_per_second must be positive")
    if orientation_mode not in {"continuous", "circuit_step"}:
        raise ValueError("orientation_mode must be 'continuous' or 'circuit_step'")
    if retained_circuits < 0:
        raise ValueError("retained_circuits must be non-negative")
    if not 0 <= retention_fade <= 1:
        raise ValueError("retention_fade must be between 0 and 1")

    continuous_pitch = base_pitch_degrees + pitch_degrees_per_second * motion_time
    continuous_yaw = base_yaw_degrees + yaw_degrees_per_second * motion_time
    completed = 0
    if orientation_mode == "circuit_step":
        # The epsilon stabilizes an exact circuit boundary after floating-point
        # interpolation without causing a visibly early step.
        completed = math.floor(trace_time * cycles_per_second + 1e-9)

    def _orientation(step_index: int, opacity: float = 1.0) -> SpatialOrientation:
        return SpatialOrientation(
            pitch_radians=math.radians(
                continuous_pitch + pitch_step_degrees * step_index
            ),
            yaw_radians=math.radians(
                continuous_yaw + yaw_step_degrees * step_index
            ),
            opacity=opacity,
        )

    current = _orientation(completed)
    retained = retained_spatial_orientations(
        current_pitch_radians=current.pitch_radians,
        current_yaw_radians=current.yaw_radians,
        trace_time=trace_time,
        cycles_per_second=cycles_per_second,
        orientation_mode=orientation_mode,
        pitch_step_degrees=pitch_step_degrees,
        yaw_step_degrees=yaw_step_degrees,
        retained_circuits=retained_circuits,
        retention_fade=retention_fade,
    )
    return current, retained


def lift_curve_points(
    points: NDArray[np.float32],
    progress: NDArray[np.float32],
    *,
    mode: str,
    amplitude: float,
    windings: int,
    phase_degrees: float,
) -> NDArray[np.float32]:
    """Lift normalized x/y points into x/y/z actor space.

    Planar curves receive z=0. A wave uses whole windings over normalized
    curve progress, so a closed curve remains closed in all three dimensions.
    """
    if points.ndim != 2 or points.shape[1] != 2:
        raise ValueError("points must have shape (n, 2)")
    if progress.ndim != 1 or len(progress) != len(points):
        raise ValueError("progress must have shape (n,)")
    if mode not in {"tilted", "wave"}:
        raise ValueError("mode must be 'tilted' or 'wave'")

    lifted = np.zeros((len(points), 3), dtype=np.float32)
    lifted[:, :2] = points
    if mode == "wave":
        phase = math.radians(phase_degrees)
        lifted[:, 2] = amplitude * np.sin(math.tau * windings * progress + phase)
    if not np.isfinite(lifted).all():
        raise ValueError("lifted points must be finite")
    lifted.setflags(write=False)
    return lifted


def project_curve_points(
    points: NDArray[np.float32],
    *,
    pitch_radians: float,
    yaw_radians: float,
    roll_radians: float,
    perspective_strength: float,
) -> tuple[NDArray[np.float32], NDArray[np.float32]]:
    """Rotate 3D actor points, then project them onto the frame plane.

    Positive z is nearer the camera. The returned depth cue is stable in
    [0, 1] and is used only for visual stroke cues; projected pixels remain
    the renderer's geometric authority.
    """
    if points.ndim != 2 or points.shape[1] != 3:
        raise ValueError("points must have shape (n, 3)")
    if not 0 <= perspective_strength <= 0.35:
        raise ValueError("perspective_strength must be between 0 and 0.35")

    pitch_cosine = math.cos(pitch_radians)
    pitch_sine = math.sin(pitch_radians)
    yaw_cosine = math.cos(yaw_radians)
    yaw_sine = math.sin(yaw_radians)
    roll_cosine = math.cos(roll_radians)
    roll_sine = math.sin(roll_radians)

    x = points[:, 0]
    y = points[:, 1] * pitch_cosine - points[:, 2] * pitch_sine
    z = points[:, 1] * pitch_sine + points[:, 2] * pitch_cosine
    yaw_x = x * yaw_cosine + z * yaw_sine
    yaw_z = -x * yaw_sine + z * yaw_cosine
    roll_x = yaw_x * roll_cosine - y * roll_sine
    roll_y = yaw_x * roll_sine + y * roll_cosine

    perspective = 1 / np.maximum(0.25, 1 - perspective_strength * yaw_z)
    projected = np.column_stack((roll_x * perspective, roll_y * perspective)).astype(
        np.float32
    )
    # Normalized input x/y and z amplitude are each bounded by one. Using the
    # fixed 3D bound avoids a trace window changing its own depth contrast.
    depth = np.clip(0.5 + yaw_z / (2 * math.sqrt(2)), 0, 1).astype(np.float32)
    if not np.isfinite(projected).all() or not np.isfinite(depth).all():
        raise ValueError("projected points must be finite")
    projected.setflags(write=False)
    depth.setflags(write=False)
    return projected, depth
