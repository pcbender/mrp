from dataclasses import dataclass

import numpy as np
from numpy.typing import NDArray


@dataclass(frozen=True, slots=True)
class TraceWindow:
    points: NDArray[np.float32]
    progress: float
    indices: NDArray[np.int64] | None = None
    """Source-point indices of the window, for per-point lookups (color flow)."""

    @property
    def head(self) -> NDArray[np.float32]:
        return self.points[-1]


def trace_progress(
    time_seconds: float,
    cycles_per_second: float,
    *,
    phase: float = 0,
) -> float:
    """Return a stable cyclic pen position derived only from song time."""
    if time_seconds < 0:
        raise ValueError("time_seconds must be non-negative")
    if cycles_per_second <= 0:
        raise ValueError("cycles_per_second must be positive")
    return (phase + time_seconds * cycles_per_second) % 1


def cyclic_trace_window(
    points: NDArray[np.float32],
    progress: float,
    trail_fraction: float,
) -> TraceWindow:
    """Select a tail-to-head window from a closed curve, including wraparound."""
    if points.ndim != 2 or points.shape[1] not in {2, 3} or len(points) < 2:
        raise ValueError("points must have shape (n, 2|3) with at least two points")
    if not 0 < trail_fraction <= 1:
        raise ValueError("trail_fraction must be within (0, 1]")

    core = points[:-1] if np.allclose(points[0], points[-1]) else points
    point_count = len(core)
    if point_count < 2:
        raise ValueError("closed curve must contain at least two distinct samples")

    normalized_progress = progress % 1
    head_index = round(normalized_progress * point_count) % point_count
    trail_count = min(point_count, max(2, round(point_count * trail_fraction)))
    indices = np.arange(head_index - trail_count + 1, head_index + 1) % point_count
    selected = np.asarray(core[indices], dtype=np.float32)
    selected.setflags(write=False)
    indices.setflags(write=False)
    return TraceWindow(points=selected, progress=normalized_progress, indices=indices)
