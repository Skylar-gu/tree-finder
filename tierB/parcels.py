"""Parcel / land-use + hazard reconciliation (spec §4.2).

This is Tier B's product-load-bearing half. It does **not** produce a
climbability signal; it produces:

  1. an eligibility **gate** — ``public_flag`` from land-use / parcel containment
     (private parcel -> excluded, per invariant #3), and
  2. score **penalties** — proximity to hazards (OSM ``power=line``/``tower``,
     ``highway``, ``waterway``) as graded multiplicative penalties (spec §4.2).

Geometry is taken from OSM. :class:`OsmContext` is fed either live (Overpass) or
from a bundled GeoJSON so tests and demos are fully offline. Only the fetch step
touches the network; all reconciliation logic below is pure.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional, Sequence

from .geometry import Point, Ring, point_in_polygon, point_to_line_m

# --- Tunable classification tables (NOT physical truths; calibrate later) -----

# Land-use / leisure tags that mean "public, eligible" vs "private, gate out".
PUBLIC_TAGS = {
    ("leisure", "park"), ("leisure", "garden"), ("leisure", "recreation_ground"),
    ("leisure", "nature_reserve"), ("landuse", "grass"), ("landuse", "forest"),
    ("landuse", "recreation_ground"), ("landuse", "village_green"),
    ("landuse", "cemetery"), ("boundary", "national_park"),
}
PRIVATE_TAGS = {
    ("landuse", "residential"), ("landuse", "commercial"), ("landuse", "retail"),
    ("landuse", "industrial"), ("landuse", "farmyard"), ("landuse", "military"),
    ("leisure", "garden;private"),
}

# Hazard proximity penalty bands: (max_distance_m, penalty_multiplier).
# A tree within the tightest band of a hazard is heavily de-ranked; the effect
# fades with distance and never zeroes a score by itself (exclusion is separate).
HAZARD_BANDS: dict[str, list[tuple[float, float]]] = {
    "power_line": [(6.0, 0.25), (15.0, 0.6), (30.0, 0.85)],
    "highway":    [(4.0, 0.5), (10.0, 0.8)],
    "waterway":   [(3.0, 0.6), (8.0, 0.85)],
}


@dataclass
class PolygonFeature:
    tag: tuple[str, str]                  # (key, value), e.g. ("leisure", "park")
    polygon: Sequence[Ring]               # [outer, *holes] in lon/lat


@dataclass
class LineFeature:
    kind: str                             # "power_line" | "highway" | "waterway"
    line: Sequence[Point]                 # polyline in lon/lat


@dataclass
class OsmContext:
    """Local OSM geometry near a query area, from Overpass or a GeoJSON file."""
    polygons: list[PolygonFeature] = field(default_factory=list)
    lines: list[LineFeature] = field(default_factory=list)


@dataclass
class Hazard:
    kind: str
    distance_m: float
    penalty: float


@dataclass
class EligibilityResult:
    """Tier B assessment for one tree — gate + penalty, never a climb score."""
    public_flag: bool
    excluded: bool
    exclusion_reason: Optional[str]
    hazards: list[Hazard]
    penalty: float                        # multiplicative in [0,1]; 1.0 = none
    penalty_reasons: list[str]
    detected: bool                        # aerial-detected (no inventory)?
    tiers: list[str]

    def to_dict(self) -> dict:
        return {
            "public_flag": self.public_flag,
            "excluded": self.excluded,
            "exclusion_reason": self.exclusion_reason,
            "hazards": [h.__dict__ for h in self.hazards],
            "penalty": round(self.penalty, 4),
            "penalty_reasons": self.penalty_reasons,
            "detected": self.detected,
            "tiers": self.tiers,
        }


def _band_penalty(kind: str, distance_m: float) -> Optional[float]:
    """Penalty multiplier for a hazard of ``kind`` at ``distance_m``, or None."""
    for max_d, mult in HAZARD_BANDS.get(kind, []):
        if distance_m <= max_d:
            return mult
    return None


def assess_eligibility(
    lon: float,
    lat: float,
    ctx: OsmContext,
    *,
    incoming_public_flag: Optional[bool] = None,
    detected: bool = False,
) -> EligibilityResult:
    """Reconcile one tree location against OSM land-use + hazards.

    ``incoming_public_flag`` is the source's own belief (inventory trees default
    True, being government street/park trees). Tier B refines it: a point inside
    an explicitly private parcel is excluded; inside a public land-use it is
    confirmed public. Aerial-detected trees (``detected=True``) have no such
    prior, so containment decides.
    """
    pt: Point = (lon, lat)

    # --- Gate: public vs private via land-use containment ---------------------
    in_private = any(
        f.tag in PRIVATE_TAGS and point_in_polygon(pt, f.polygon)
        for f in ctx.polygons
    )
    in_public = any(
        f.tag in PUBLIC_TAGS and point_in_polygon(pt, f.polygon)
        for f in ctx.polygons
    )

    if in_private and not in_public:
        public_flag = False
    elif in_public:
        public_flag = True
    else:
        # No decisive containment: keep the source's prior (or assume public for
        # inventory trees, which are already biased to public street/park stock).
        public_flag = True if incoming_public_flag is None else incoming_public_flag

    excluded = not public_flag
    exclusion_reason = "inside private parcel/land-use" if excluded else None

    # --- Penalties: hazard proximity -----------------------------------------
    hazards: list[Hazard] = []
    penalty = 1.0
    penalty_reasons: list[str] = []
    for f in ctx.lines:
        dist = point_to_line_m(pt, f.line)
        mult = _band_penalty(f.kind, dist)
        if mult is not None:
            hazards.append(Hazard(kind=f.kind, distance_m=round(dist, 2), penalty=mult))
            penalty *= mult
            penalty_reasons.append(
                f"{f.kind.replace('_', ' ')} within {dist:.1f} m (×{mult})"
            )

    tiers = ["B:parcels"]
    if detected:
        tiers.insert(0, "B:aerial")

    return EligibilityResult(
        public_flag=public_flag,
        excluded=excluded,
        exclusion_reason=exclusion_reason,
        hazards=hazards,
        penalty=round(penalty, 4),
        penalty_reasons=penalty_reasons,
        detected=detected,
        tiers=tiers,
    )


# --- OSM loading --------------------------------------------------------------

def context_from_geojson(geojson: dict) -> OsmContext:
    """Build an :class:`OsmContext` from a GeoJSON FeatureCollection.

    Polygons are classified by their ``leisure``/``landuse``/``boundary``
    properties; LineStrings by ``power``/``highway``/``waterway``. This is the
    offline path used by tests and the bundled demo (no network).
    """
    polygons: list[PolygonFeature] = []
    lines: list[LineFeature] = []
    for feat in geojson.get("features", []):
        geom = feat.get("geometry") or {}
        props = feat.get("properties") or {}
        gtype = geom.get("type")
        coords = geom.get("coordinates") or []

        if gtype == "Polygon":
            tag = _polygon_tag(props)
            if tag:
                polygons.append(PolygonFeature(tag=tag, polygon=coords))
        elif gtype == "MultiPolygon":
            tag = _polygon_tag(props)
            if tag:
                for poly in coords:
                    polygons.append(PolygonFeature(tag=tag, polygon=poly))
        elif gtype == "LineString":
            kind = _line_kind(props)
            if kind:
                lines.append(LineFeature(kind=kind, line=coords))
        elif gtype == "MultiLineString":
            kind = _line_kind(props)
            if kind:
                for ln in coords:
                    lines.append(LineFeature(kind=kind, line=ln))
    return OsmContext(polygons=polygons, lines=lines)


def _polygon_tag(props: dict) -> Optional[tuple[str, str]]:
    for key in ("leisure", "landuse", "boundary"):
        if key in props and props[key] is not None:
            return (key, str(props[key]))
    return None


def _line_kind(props: dict) -> Optional[str]:
    if props.get("power") in {"line", "minor_line", "cable"}:
        return "power_line"
    if props.get("highway"):
        return "highway"
    if props.get("waterway"):
        return "waterway"
    return None
