import numpy as np
import pytest

from mrp.video.tracing import cyclic_trace_window, trace_progress


def _closed_square() -> np.ndarray:
    return np.asarray(
        ((0, 0), (1, 0), (1, 1), (0, 1), (0, 0)),
        dtype=np.float32,
    )


def test_trace_progress_is_deterministic_and_wraps() -> None:
    assert trace_progress(2.5, 0.2, phase=0.1) == pytest.approx(0.6)
    assert trace_progress(7.5, 0.2, phase=0.1) == pytest.approx(0.6)


def test_trace_window_selects_tail_to_head_without_closing_the_curve() -> None:
    window = cyclic_trace_window(_closed_square(), 0.5, 0.5)

    np.testing.assert_array_equal(window.points, ((1, 0), (1, 1)))
    np.testing.assert_array_equal(window.head, (1, 1))


def test_trace_window_wraps_around_curve_start() -> None:
    window = cyclic_trace_window(_closed_square(), 0, 0.75)

    np.testing.assert_array_equal(window.points, ((1, 1), (0, 1), (0, 0)))


def test_trace_window_preserves_three_dimensional_points() -> None:
    points = np.column_stack(
        (_closed_square(), np.asarray((0, 0.5, 0, -0.5, 0), dtype=np.float32))
    )

    window = cyclic_trace_window(points, 0.5, 0.5)

    np.testing.assert_array_equal(window.points, ((1, 0, 0.5), (1, 1, 0)))
    assert window.points.shape == (2, 3)


@pytest.mark.parametrize("trail_fraction", [0, -0.1, 1.1])
def test_trace_window_rejects_invalid_fraction(trail_fraction: float) -> None:
    with pytest.raises(ValueError, match="trail_fraction"):
        cyclic_trace_window(_closed_square(), 0.5, trail_fraction)
