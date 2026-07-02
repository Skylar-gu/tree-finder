"""Live OSM fetch (Overpass) -> OsmContext for eligibility/hazard reconciliation.

Fetches land-use/parcel polygons (for the public/private gate) and power lines
(the meaningful hazard for street trees) around a point, and builds the same
:class:`OsmContext` the offline path uses. Network is confined to
:func:`fetch_osm_context`, which takes an injectable ``fetch`` so tests/offline
runs never hit the network.

NOTE on roads: we deliberately do NOT pull highways as hazards on the live path —
street trees are by definition metres from a road, so a road-proximity penalty
would de-rank essentially everything. Power lines are the discriminating hazard.
"""

from __future__ import annotations

import math
from typing import Callable, Optional

from .parcels import LineFeature, OsmContext, PolygonFeature

import os

# Public Overpass mirrors, tried in order (override with OVERPASS_URL).
OVERPASS_URLS = [
    os.getenv("OVERPASS_URL", "https://overpass-api.de/api/interpreter"),
    "https://overpass.kumi.systems/api/interpreter",
    "https://maps.mail.ru/osm/tools/overpass/api/interpreter",
]
_UA = "climbable-trees/1.0 (tree eligibility/hazard reconciliation)"

# Land-use/leisure tags we care about (gate), plus power lines (hazard).
_QUERY_TMPL = """[out:json][timeout:40];
(
  way["landuse"="residential"]({bbox});
  way["landuse"="commercial"]({bbox});
  way["landuse"="industrial"]({bbox});
  way["leisure"="park"]({bbox});
  way["power"="line"]({bbox});
);
out geom;"""


def _bbox(lon: float, lat: float, radius_m: float) -> tuple[float, float, float, float]:
    """(south, west, north, east) for an Overpass bbox around a point."""
    dlat = radius_m / 111_320.0
    dlon = radius_m / (111_320.0 * max(math.cos(math.radians(lat)), 1e-6))
    return (lat - dlat, lon - dlon, lat + dlat, lon + dlon)


def elements_to_context(elements: list[dict]) -> OsmContext:
    """Convert Overpass ``out geom`` elements into an OsmContext (pure)."""
    polygons: list[PolygonFeature] = []
    lines: list[LineFeature] = []
    for el in elements:
        if el.get("type") != "way":
            continue
        geom = el.get("geometry") or []
        coords = [(p["lon"], p["lat"]) for p in geom if "lon" in p and "lat" in p]
        if len(coords) < 2:
            continue
        tags = el.get("tags") or {}
        if "power" in tags:
            lines.append(LineFeature(kind="power_line", line=coords))
        elif "landuse" in tags:
            polygons.append(PolygonFeature(tag=("landuse", tags["landuse"]), polygon=[coords]))
        elif "leisure" in tags:
            polygons.append(PolygonFeature(tag=("leisure", tags["leisure"]), polygon=[coords]))
    return OsmContext(polygons=polygons, lines=lines)


def fetch_osm_context(
    lon: float,
    lat: float,
    radius_m: float,
    *,
    fetch: Optional[Callable] = None,
) -> OsmContext:
    """Fetch OSM land-use + power lines near a point and build an OsmContext.

    ``fetch(url, data) -> dict`` is injectable; the default uses ``requests``.
    Returns an empty context on any failure (reconciliation then no-ops).
    """
    s, w, n, e = _bbox(lon, lat, radius_m)
    query = _QUERY_TMPL.format(bbox=f"{s},{w},{n},{e}")

    if fetch is not None:
        try:
            return elements_to_context(fetch(OVERPASS_URLS[0], query).get("elements", []))
        except Exception as exc:
            print(f"[overpass] fetch failed ({exc}); skipping reconciliation")
            return OsmContext()

    import requests

    last = None
    for url in OVERPASS_URLS:
        try:
            resp = requests.post(
                url,
                data={"data": query},
                headers={"User-Agent": _UA, "Accept": "application/json"},
                timeout=45,
            )
            resp.raise_for_status()
            return elements_to_context(resp.json().get("elements", []))
        except Exception as exc:  # try the next mirror
            last = exc
            continue
    print(f"[overpass] all mirrors failed ({last}); skipping reconciliation")
    return OsmContext()
