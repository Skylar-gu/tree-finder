"""Small dependency-free geometry helpers for Tier B reconciliation.

Tier B needs two spatial primitives that must run without shapely (which is an
optional extra): point-in-polygon (for parcel / land-use containment) and
point-to-polyline distance in metres (for hazard proximity to power lines,
roads, waterways).

Distances use a local equirectangular projection around the query point. Over
the tens-of-metres ranges Tier B cares about this is accurate to well under a
percent, and it avoids a geodesic dependency. Everything here is pure.
"""

from __future__ import annotations

import math
from typing import Sequence

# ~metres per degree latitude (constant); longitude scales by cos(lat).
_M_PER_DEG_LAT = 111_320.0

Point = tuple[float, float]          # (lon, lat)
Ring = Sequence[Point]               # closed or open ring of (lon, lat)


def _local_xy(pt: Point, origin: Point) -> tuple[float, float]:
    """Project ``pt`` to local metres east/north of ``origin`` (equirectangular)."""
    lon, lat = pt
    olon, olat = origin
    m_per_deg_lon = _M_PER_DEG_LAT * math.cos(math.radians(olat))
    return ((lon - olon) * m_per_deg_lon, (lat - olat) * _M_PER_DEG_LAT)


def haversine_m(a: Point, b: Point) -> float:
    """Great-circle distance between two (lon, lat) points, in metres."""
    lon1, lat1 = a
    lon2, lat2 = b
    r = 6_371_000.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp = math.radians(lat2 - lat1)
    dl = math.radians(lon2 - lon1)
    h = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(min(1.0, math.sqrt(h)))


def point_in_ring(pt: Point, ring: Ring) -> bool:
    """Ray-casting point-in-ring test (ring in lon/lat; winding-agnostic)."""
    lon, lat = pt
    inside = False
    n = len(ring)
    if n < 3:
        return False
    j = n - 1
    for i in range(n):
        xi, yi = ring[i]
        xj, yj = ring[j]
        # Does the horizontal ray at ``lat`` cross edge (i, j)?
        if (yi > lat) != (yj > lat):
            x_cross = xi + (lat - yi) / (yj - yi) * (xj - xi)
            if lon < x_cross:
                inside = not inside
        j = i
    return inside


def point_in_polygon(pt: Point, polygon: Sequence[Ring]) -> bool:
    """Point-in-polygon with holes. ``polygon[0]`` is the outer ring; the rest
    are holes. Returns True iff inside the outer ring and outside every hole."""
    if not polygon:
        return False
    if not point_in_ring(pt, polygon[0]):
        return False
    for hole in polygon[1:]:
        if point_in_ring(pt, hole):
            return False
    return True


def _point_to_segment_m(pt: Point, a: Point, b: Point) -> float:
    """Distance in metres from ``pt`` to segment ``a``-``b`` (local projection)."""
    px, py = _local_xy(pt, pt)          # = (0, 0)
    ax, ay = _local_xy(a, pt)
    bx, by = _local_xy(b, pt)
    dx, dy = bx - ax, by - ay
    seg_len2 = dx * dx + dy * dy
    if seg_len2 == 0.0:
        return math.hypot(ax, ay)       # degenerate segment == point a
    # Projection parameter of pt onto the segment, clamped to [0, 1].
    t = max(0.0, min(1.0, ((px - ax) * dx + (py - ay) * dy) / seg_len2))
    cx, cy = ax + t * dx, ay + t * dy
    return math.hypot(px - cx, py - cy)


def point_to_line_m(pt: Point, line: Sequence[Point]) -> float:
    """Minimum distance in metres from ``pt`` to a polyline (>=1 vertex)."""
    if not line:
        return math.inf
    if len(line) == 1:
        return haversine_m(pt, line[0])
    return min(
        _point_to_segment_m(pt, line[i], line[i + 1])
        for i in range(len(line) - 1)
    )
