import math
import sys
from dataclasses import dataclass
from typing import Literal

RotationMode = Literal["inside", "outside"]
TAU = math.tau


@dataclass(frozen=True, slots=True)
class SpiroGeometry:
    """Geometry for one curve; ``family`` selects which fields apply.

    Curve math is mirrored in mrp/admin/static/spiro-preview.js — keep the
    closure formulas and expressions in sync.
    """

    fixed_radius: float | None = None
    moving_radius: float | None = None
    pen_offset: float | None = None
    phase: float = 0.0
    rotation: RotationMode = "inside"
    samples: float = 900
    family: str = "spirogram"
    # lissajous: x = sin(a*theta + delta), y = sin(b*theta)
    liss_freq_x: int = 3
    liss_freq_y: int = 2
    liss_delta: float = math.pi / 2
    # rose: r = cos((n/d) * theta)
    rose_n: int = 5
    rose_d: int = 1
    # superformula (Gielis, a = b = 1)
    sf_m: int = 6
    sf_n1: float = 0.3
    sf_n2: float = 0.3
    sf_n3: float = 0.3


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


def _spirogram_curve(geometry: SpiroGeometry):
    """Trochoid curve, identical to the archived TypeScript prototype."""
    end = _cycle_end(geometry.fixed_radius, geometry.moving_radius)
    if geometry.rotation == "inside":

        def point(theta: float) -> tuple[float, float]:
            return _hypotrochoid_point(
                theta,
                geometry.fixed_radius,
                geometry.moving_radius,
                geometry.pen_offset,
            )

    else:

        def point(theta: float) -> tuple[float, float]:
            return _epitrochoid_point(
                theta,
                geometry.fixed_radius,
                geometry.moving_radius,
                geometry.pen_offset,
            )

    return end, point


def _lissajous_curve(geometry: SpiroGeometry):
    """x = sin(a*theta + delta), y = sin(b*theta); closes at TAU / gcd(a, b)."""
    a = max(1, _javascript_round(geometry.liss_freq_x))
    b = max(1, _javascript_round(geometry.liss_freq_y))
    delta = geometry.liss_delta
    end = TAU / greatest_common_divisor(a, b)

    def point(theta: float) -> tuple[float, float]:
        return math.sin(a * theta + delta), math.sin(b * theta)

    return end, point


def _rose_curve(geometry: SpiroGeometry):
    """r = cos(k*theta), k = n/d reduced; closes at pi*d (n*d odd) else 2*pi*d."""
    n = max(1, _javascript_round(geometry.rose_n))
    d = max(1, _javascript_round(geometry.rose_d))
    divisor = greatest_common_divisor(n, d)
    n //= divisor
    d //= divisor
    end = math.pi * d if (n * d) % 2 == 1 else TAU * d
    k = n / d

    def point(theta: float) -> tuple[float, float]:
        radius = math.cos(k * theta)
        return radius * math.cos(theta), radius * math.sin(theta)

    return end, point


def _superformula_curve(geometry: SpiroGeometry):
    """Gielis supershape with a = b = 1; closes at TAU (m even or 0) else 2*TAU."""
    m = max(0, _javascript_round(geometry.sf_m))
    n1, n2, n3 = geometry.sf_n1, geometry.sf_n2, geometry.sf_n3
    end = TAU if m % 2 == 0 else 2 * TAU

    def point(theta: float) -> tuple[float, float]:
        u = m * theta / 4
        base = abs(math.cos(u)) ** n2 + abs(math.sin(u)) ** n3
        try:
            radius = base ** (-1 / n1)
        except (OverflowError, ZeroDivisionError):
            radius = 0.0
        if not math.isfinite(radius):
            radius = 0.0
        radius = min(radius, 1e9)
        return radius * math.cos(theta), radius * math.sin(theta)

    return end, point


_CURVE_FAMILIES = {
    "spirogram": _spirogram_curve,
    "lissajous": _lissajous_curve,
    "rose": _rose_curve,
    "superformula": _superformula_curve,
}


def generate_spiro_points(geometry: SpiroGeometry) -> list[SpiroPoint]:
    """Generate one closed curve for the geometry's family.

    The spirogram branch produces the same trochoid points as the archived
    TypeScript prototype; other families share the identical sampling loop
    (theta = progress * end + phase) so phase, color flow, and tracing behave
    uniformly.
    """
    curve = _CURVE_FAMILIES.get(geometry.family)
    if curve is None:
        raise ValueError(f"unknown geometry family: {geometry.family}")
    end, point_at = curve(geometry)
    point_count = max(2, _javascript_round(geometry.samples))
    points: list[SpiroPoint] = []

    for index in range(point_count):
        progress = index / (point_count - 1)
        theta = progress * end + geometry.phase
        x, y = point_at(theta)

        points.append(
            SpiroPoint(
                t=progress,
                x=x,
                y=y,
                radius=math.hypot(x, y),
                angle=math.atan2(y, x),
            )
        )

    if geometry.family != "spirogram" and len(points) > 1:
        # Every family closes by construction, but fractional exponents (e.g.
        # superformula n3 < 1) amplify float residue at the wrap point. Snap
        # the endpoint so the tracing window's closed-curve trim fires
        # deterministically. The spirogram branch is left verbatim to keep
        # its golden fixture and render digests byte-identical.
        first = points[0]
        points[-1] = SpiroPoint(
            t=1.0,
            x=first.x,
            y=first.y,
            radius=first.radius,
            angle=first.angle,
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
