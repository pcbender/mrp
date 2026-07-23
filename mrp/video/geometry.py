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
    # path: one SVG subpath's d attribute, resampled by arc length
    path_data: str = ""
    # harmonograph: damped lissajous, ping-ponged closed
    harm_freq_x: float = 3.01
    harm_freq_y: float = 2.0
    harm_delta: float = math.pi / 2
    harm_damping: float = 0.02
    harm_turns: int = 12


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


def _harmonograph_points(geometry: SpiroGeometry) -> list[SpiroPoint]:
    """Damped lissajous traced forward, then ping-ponged into a closed cycle.

    x = sin(fx*theta + delta) * exp(-damping*theta), y = sin(fy*theta) *
    exp(-damping*theta) over turns full windings. The decay makes the curve
    open, so like open SVG subpaths it samples the forward half and retraces
    the interior in reverse — a seamless palindrome whose endpoint lands
    exactly on its start. theta = progress * end + phase keeps the shared
    start-offset meaning of phase. Mirrored by mrpSpiroPoints in
    mrp/admin/static/spiro-preview.js — keep the two in sync.
    """
    end = max(1, _javascript_round(geometry.harm_turns)) * TAU
    count = max(2, _javascript_round(geometry.samples))
    forward = count // 2 + 1
    xs: list[float] = []
    ys: list[float] = []
    for index in range(forward):
        theta = index / (forward - 1) * end + geometry.phase
        envelope = math.exp(-geometry.harm_damping * theta)
        xs.append(math.sin(geometry.harm_freq_x * theta + geometry.harm_delta) * envelope)
        ys.append(math.sin(geometry.harm_freq_y * theta) * envelope)
    xs += xs[-2::-1]
    ys += ys[-2::-1]

    points: list[SpiroPoint] = []
    last = len(xs) - 1
    for position, (x, y) in enumerate(zip(xs, ys)):
        points.append(
            SpiroPoint(
                t=position / last,
                x=x,
                y=y,
                radius=math.hypot(x, y),
                angle=math.atan2(y, x),
            )
        )
    return points


def _path_points(geometry: SpiroGeometry) -> list[SpiroPoint]:
    """Trace one SVG subpath as a closed cycle of arc-length-uniform points.

    SVG's y axis grows downward, exactly like the admin canvas and the cv2
    frame buffer, so coordinates pass through without a y-flip. A closed
    subpath is resampled to ``samples`` stations with the endpoint snapped
    onto the start; an open subpath is sampled halfway and ping-ponged
    (forward then back over the interior) so the cycle has no seam. Points
    are centered on the sampled bounding-box center because the renderer
    normalizes and places curves about the origin. ``phase`` rotates the
    start point around the cycle, matching its start-offset meaning in the
    parametric families. The sampler is mirrored by mrpPathPoints in
    mrp/admin/static/spiro-preview.js — keep the two in sync.
    """
    import numpy as np
    from svgpathtools import parse_path

    subpaths = [
        subpath
        for subpath in parse_path(geometry.path_data).continuous_subpaths()
        if len(subpath)
    ]
    if len(subpaths) != 1:
        raise ValueError(
            f"path geometry requires exactly one subpath, found {len(subpaths)}"
        )
    subpath = subpaths[0]
    count = max(2, _javascript_round(geometry.samples))

    # Degenerate paths crash svgpathtools' arc-length inversion, so check the
    # bounding box before sampling.
    xmin, xmax, ymin, ymax = subpath.bbox()
    diagonal = math.hypot(xmax - xmin, ymax - ymin)
    if diagonal <= 0:
        raise ValueError("path geometry has no extent")

    # Oversample uniformly in path parameter, then measure chord lengths so
    # the final stations are uniform in arc length. 4x oversampling keeps the
    # chord interpolation error on curved segments below preview resolution.
    oversample = max(4 * count, 512)
    raw = np.asarray(
        [subpath.point(index / (oversample - 1)) for index in range(oversample)]
    )
    xs, ys = raw.real, raw.imag
    closed = bool(subpath.isclosed()) or abs(raw[-1] - raw[0]) < 1e-6 * diagonal
    lengths = np.concatenate([[0.0], np.cumsum(np.abs(np.diff(raw)))])
    total = float(lengths[-1])
    if total <= 0:
        raise ValueError("path geometry has no length")

    if closed:
        stations = np.linspace(0.0, total, count)
        px = np.interp(stations, lengths, xs)
        py = np.interp(stations, lengths, ys)
        px[-1], py[-1] = px[0], py[0]
    else:
        forward = count // 2 + 1
        stations = np.linspace(0.0, total, forward)
        fx = np.interp(stations, lengths, xs)
        fy = np.interp(stations, lengths, ys)
        px = np.concatenate([fx, fx[-2::-1]])
        py = np.concatenate([fy, fy[-2::-1]])

    px = px - (px.max() + px.min()) / 2
    py = py - (py.max() + py.min()) / 2

    cycle = len(px) - 1
    fraction = ((geometry.phase % TAU) + TAU) % TAU / TAU
    shift = _javascript_round(fraction * cycle) % cycle
    order = [(shift + index) % cycle for index in range(cycle)] + [shift % cycle]

    points: list[SpiroPoint] = []
    last = len(order) - 1
    for position, index in enumerate(order):
        x, y = float(px[index]), float(py[index])
        points.append(
            SpiroPoint(
                t=position / last,
                x=x,
                y=y,
                radius=math.hypot(x, y),
                angle=math.atan2(y, x),
            )
        )
    return points


def _contour_stations(subpath: object, count: int):
    """Arc-length-uniform (px, py) stations for one subpath, positioned.

    Same sampling as _path_points but WITHOUT centering — text keeps each
    glyph-contour where the wordmark places it, and the group is normalized
    together later. Returns (px, py, arc_length) or None for a degenerate
    contour.
    """
    import numpy as np

    xmin, xmax, ymin, ymax = subpath.bbox()
    diagonal = math.hypot(xmax - xmin, ymax - ymin)
    if diagonal <= 0:
        return None
    oversample = max(4 * count, 512)
    raw = np.asarray([subpath.point(i / (oversample - 1)) for i in range(oversample)])
    lengths = np.concatenate([[0.0], np.cumsum(np.abs(np.diff(raw)))])
    total = float(lengths[-1])
    if total <= 0:
        return None
    closed = bool(subpath.isclosed()) or abs(raw[-1] - raw[0]) < 1e-6 * diagonal
    if closed:
        stations = np.linspace(0.0, total, count)
        px = np.interp(stations, lengths, raw.real)
        py = np.interp(stations, lengths, raw.imag)
        px[-1], py[-1] = px[0], py[0]
    else:
        forward = count // 2 + 1
        stations = np.linspace(0.0, total, forward)
        fx = np.interp(stations, lengths, raw.real)
        fy = np.interp(stations, lengths, raw.imag)
        px = np.concatenate([fx, fx[-2::-1]])
        py = np.concatenate([fy, fy[-2::-1]])
    return px, py, total


def generate_text_points(geometry: SpiroGeometry) -> list[list[SpiroPoint]]:
    """Sample a multi-subpath ``text`` path into one traced cycle per contour.

    Each letter-contour becomes its own closed cycle (so the renderer draws a
    per-letter spiro trail), and all contours are normalized as a GROUP — the
    whole word is centered on its bounding box and divided by a single extent,
    so letters keep their relative position and size. Mirrors mrpTextContours
    in mrp/admin/static/spiro-preview.js — keep the two in sync.
    """
    import numpy as np
    from svgpathtools import parse_path

    subpaths = [
        subpath
        for subpath in parse_path(geometry.path_data).continuous_subpaths()
        if len(subpath)
    ]
    if not subpaths:
        raise ValueError("text geometry requires at least one subpath")
    count = max(2, _javascript_round(geometry.samples))

    sampled: list[tuple] = []
    for subpath in subpaths:
        stations = _contour_stations(subpath, count)
        if stations is not None:
            sampled.append(stations)
    if not sampled:
        raise ValueError("text geometry has no drawable extent")

    all_x = np.concatenate([px for px, _py, _t in sampled])
    all_y = np.concatenate([py for _px, py, _t in sampled])
    center_x = (float(all_x.max()) + float(all_x.min())) / 2
    center_y = (float(all_y.max()) + float(all_y.min())) / 2
    extent = 0.0
    for px, py, _total in sampled:
        extent = max(extent, float(np.max(np.hypot(px - center_x, py - center_y))))
    if extent <= 0:
        raise ValueError("text geometry has no extent")

    contours: list[list[SpiroPoint]] = []
    for px, py, _total in sampled:
        nx = (px - center_x) / extent
        ny = (py - center_y) / extent
        last = max(1, len(nx) - 1)
        contour = [
            SpiroPoint(
                t=index / last,
                x=float(nx[index]),
                y=float(ny[index]),
                radius=math.hypot(float(nx[index]), float(ny[index])),
                angle=math.atan2(float(ny[index]), float(nx[index])),
            )
            for index in range(len(nx))
        ]
        contours.append(contour)
    return contours


_CURVE_FAMILIES = {
    "spirogram": _spirogram_curve,
    "lissajous": _lissajous_curve,
    "rose": _rose_curve,
    "superformula": _superformula_curve,
}


def generate_spiro_points(geometry: SpiroGeometry) -> list[SpiroPoint]:
    """Generate one closed curve for the geometry's family.

    The spirogram branch produces the same trochoid points as the archived
    TypeScript prototype; the other parametric families share the identical
    sampling loop (theta = progress * end + phase) so phase, color flow, and
    tracing behave uniformly. The path family is sampled by arc length in
    _path_points and the harmonograph's damped open curve is ping-ponged in
    _harmonograph_points, both keeping phase's start-offset role.
    """
    if geometry.family == "path":
        return _path_points(geometry)
    if geometry.family == "harmonograph":
        return _harmonograph_points(geometry)
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
