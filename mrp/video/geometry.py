import math
import sys
from dataclasses import dataclass
from typing import Literal

RotationMode = Literal["inside", "outside"]
TAU = math.tau


@dataclass(frozen=True, slots=True)
class SpiroGeometry:
    fixed_radius: float
    moving_radius: float
    pen_offset: float
    phase: float = 0.0
    rotation: RotationMode = "inside"
    samples: float = 900


@dataclass(frozen=True, slots=True)
class SpiroPoint:
    t: float
    x: float
    y: float
    radius: float
    angle: float


def _javascript_round(value: float) -> int:
    """Match JavaScript Math.round for finite values used by the prototype."""
    return math.floor(value + 0.5)


def _safe_divisor(value: float) -> float:
    if abs(value) < sys.float_info.epsilon:
        return -sys.float_info.epsilon if value < 0 else sys.float_info.epsilon
    return value


def greatest_common_divisor(a: float, b: float) -> int:
    x = abs(_javascript_round(a))
    y = abs(_javascript_round(b))

    while y != 0:
        x, y = y, x % y

    return x or 1


def _cycle_end(fixed_radius: float, moving_radius: float) -> float:
    fixed = max(1, _javascript_round(abs(fixed_radius)))
    moving = max(1, _javascript_round(abs(moving_radius)))
    divisor = greatest_common_divisor(fixed, moving)
    return TAU * (moving / divisor)


def _hypotrochoid_point(
    theta: float,
    fixed_radius: float,
    moving_radius: float,
    pen_offset: float,
) -> tuple[float, float]:
    radius_delta = fixed_radius - moving_radius
    ratio = radius_delta / _safe_divisor(moving_radius)
    return (
        radius_delta * math.cos(theta) + pen_offset * math.cos(ratio * theta),
        radius_delta * math.sin(theta) - pen_offset * math.sin(ratio * theta),
    )


def _epitrochoid_point(
    theta: float,
    fixed_radius: float,
    moving_radius: float,
    pen_offset: float,
) -> tuple[float, float]:
    radius_sum = fixed_radius + moving_radius
    ratio = radius_sum / _safe_divisor(moving_radius)
    return (
        radius_sum * math.cos(theta) - pen_offset * math.cos(ratio * theta),
        radius_sum * math.sin(theta) - pen_offset * math.sin(ratio * theta),
    )


def generate_spiro_points(geometry: SpiroGeometry) -> list[SpiroPoint]:
    """Generate the same trochoid points as the archived TypeScript prototype."""
    point_count = max(2, _javascript_round(geometry.samples))
    end = _cycle_end(geometry.fixed_radius, geometry.moving_radius)
    points: list[SpiroPoint] = []

    for index in range(point_count):
        progress = index / (point_count - 1)
        theta = progress * end + geometry.phase
        if geometry.rotation == "inside":
            x, y = _hypotrochoid_point(
                theta,
                geometry.fixed_radius,
                geometry.moving_radius,
                geometry.pen_offset,
            )
        else:
            x, y = _epitrochoid_point(
                theta,
                geometry.fixed_radius,
                geometry.moving_radius,
                geometry.pen_offset,
            )

        points.append(
            SpiroPoint(
                t=progress,
                x=x,
                y=y,
                radius=math.hypot(x, y),
                angle=math.atan2(y, x),
            )
        )

    return points


HueFlowSource = Literal["angle", "radius", "velocity", "curvature"]


def _normalized_angle(angle: float) -> float:
    return ((angle % TAU) + TAU) % TAU / TAU


def _signed_angle(angle: float) -> float:
    return ((angle + math.pi) % TAU) - math.pi


def _min_max_normalized(values: list[float]) -> list[float]:
    low = min(values)
    high = max(values)
    span = high - low
    # A relative guard, so a numerically-constant source (e.g. the radius of a
    # zero-pen-offset circle) collapses to the center instead of amplifying
    # float noise into a full hue swing.
    if span <= max(abs(low), abs(high), 1.0) * 1e-9:
        return [0.5 for _ in values]
    return [(value - low) / span for value in values]


def hue_flow_values(points: list[SpiroPoint], source: HueFlowSource) -> list[float]:
    """Per-point color-flow values in [0, 1], matching the archived prototype.

    The values are static per geometry; a color-flow layer maps them onto a hue
    swing centered on its resolved base color. Semantics mirror the prototype's
    pointToHue: angle normalizes the winding angle, radius and velocity are
    min-max normalized over the curve, and curvature is the absolute turn angle
    mapped over 0..pi.
    """
    if source == "angle":
        return [_normalized_angle(point.angle) for point in points]
    if source == "radius":
        return _min_max_normalized([point.radius for point in points])
    if source == "velocity":
        last = len(points) - 1
        speeds = [
            math.hypot(
                points[min(last, index + 1)].x - points[max(0, index - 1)].x,
                points[min(last, index + 1)].y - points[max(0, index - 1)].y,
            )
            for index in range(len(points))
        ]
        return _min_max_normalized(speeds)
    values = []
    for index in range(len(points)):
        if index == 0 or index == len(points) - 1:
            values.append(0.0)
            continue
        previous, current, upcoming = points[index - 1], points[index], points[index + 1]
        incoming = math.atan2(current.y - previous.y, current.x - previous.x)
        outgoing = math.atan2(upcoming.y - current.y, upcoming.x - current.x)
        values.append(abs(_signed_angle(outgoing - incoming)) / math.pi)
    return values
