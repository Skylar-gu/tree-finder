"""Mapillary API v4 client (spec §5.1).

Verified endpoints/constraints the spec pins down:
  - Auth: OAuth2 token ``MLY|...``. Query param for tiles; ``Authorization: OAuth``
    header for the Graph API.
  - Coverage: vector tiles ``https://tiles.mapillary.com/maps/vtp/mly1_public/2/
    {z}/{x}/{y}`` (max z 14). Prefer ``mly1_computed_public`` for CV-corrected
    geometry.
  - Per-image metadata: ``https://graph.mapillary.com/{image_id}?fields=...``.
    Nearest-image-to-point = fetch the overlapping tile, then filter by radius
    client-side (no server spatial query on the Graph API).
  - License [CONSTRAINT]: imagery is CC-BY-SA 4.0. Derived MEASUREMENTS are fine,
    but any displayed thumbnail needs Mapillary logo + link + contributor
    attribution. :func:`attribution_for` builds exactly that.
  - Panorama gotcha [CONSTRAINT]: many frames are 360° (``is_pano=true``);
    pinhole triangulation is invalid — filter or reproject first.

Network I/O is confined to :class:`MapillaryClient`, which takes an injectable
``fetch`` callable so tests/offline demos never hit the network.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Callable, Optional

GRAPH_FIELDS = (
    "id,thumb_2048_url,geometry,computed_geometry,compass_angle,"
    "computed_compass_angle,camera_type,camera_parameters,captured_at,"
    "sequence,is_pano,quality_score"
)

TILE_URL = "https://tiles.mapillary.com/maps/vtp/{layer}/2/{z}/{x}/{y}"
GRAPH_URL = "https://graph.mapillary.com/{image_id}"
_M_PER_DEG_LAT = 111_320.0


@dataclass
class MapillaryImage:
    image_id: str
    lon: float
    lat: float
    is_pano: bool
    camera_parameters: Optional[list[float]]
    compass_angle: Optional[float]
    captured_at: Optional[int]
    quality_score: Optional[float]
    thumb_url: Optional[str] = None
    sequence: Optional[str] = None

    @classmethod
    def from_graph(cls, d: dict) -> "MapillaryImage":
        geom = d.get("computed_geometry") or d.get("geometry") or {}
        coords = geom.get("coordinates") or [None, None]
        return cls(
            image_id=str(d.get("id")),
            lon=coords[0], lat=coords[1],
            is_pano=bool(d.get("is_pano", False)),
            camera_parameters=d.get("camera_parameters"),
            compass_angle=d.get("computed_compass_angle") or d.get("compass_angle"),
            captured_at=d.get("captured_at"),
            quality_score=d.get("quality_score"),
            thumb_url=d.get("thumb_2048_url"),
            sequence=d.get("sequence"),
        )


def attribution_for(image: MapillaryImage) -> dict:
    """CC-BY-SA 4.0 attribution block required to DISPLAY the thumbnail (§5.1).

    Measurements derived from the image need no attribution; the thumbnail does.
    """
    return {
        "provider": "Mapillary",
        "license": "CC-BY-SA 4.0",
        "license_url": "https://creativecommons.org/licenses/by-sa/4.0/",
        "image_url": f"https://www.mapillary.com/app/?pKey={image.image_id}",
        "logo_required": True,
        "note": "Display requires Mapillary logo + link + contributor credit.",
    }


def haversine_m(lon1, lat1, lon2, lat2) -> float:
    r = 6_371_000.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp = math.radians(lat2 - lat1); dl = math.radians(lon2 - lon1)
    h = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(min(1.0, math.sqrt(h)))


def lonlat_to_tile(lon: float, lat: float, z: int = 14) -> tuple[int, int]:
    """Slippy-map tile x/y for a lon/lat at zoom ``z`` (Mapillary max z=14)."""
    lat_r = math.radians(lat)
    n = 2 ** z
    x = int((lon + 180.0) / 360.0 * n)
    y = int((1.0 - math.asinh(math.tan(lat_r)) / math.pi) / 2.0 * n)
    return x, y


class MapillaryClient:
    """Thin client. ``fetch(url, params, headers) -> dict`` is injectable."""

    def __init__(self, token: str, fetch: Optional[Callable] = None):
        if not token or not token.startswith("MLY"):
            # Not fatal offline, but warn the shape is wrong.
            pass
        self.token = token
        self._fetch = fetch or self._default_fetch

    def _default_fetch(self, url, params=None, headers=None):  # pragma: no cover - net
        import requests

        resp = requests.get(url, params=params, headers=headers, timeout=30)
        resp.raise_for_status()
        return resp.json()

    def image_meta(self, image_id: str) -> MapillaryImage:
        url = GRAPH_URL.format(image_id=image_id)
        data = self._fetch(
            url,
            {"fields": GRAPH_FIELDS},
            {"Authorization": f"OAuth {self.token}"},
        )
        return MapillaryImage.from_graph(data)

    def images_in_tile(self, lon: float, lat: float, layer: str = "mly1_computed_public") -> list[dict]:
        """Fetch the vector tile overlapping (lon, lat); return raw image features.

        The default ``fetch`` would need vector-tile decoding; offline tests inject
        a ``fetch`` that returns already-decoded ``{"features": [...]}``.
        """
        x, y = lonlat_to_tile(lon, lat, z=14)
        url = TILE_URL.format(layer=layer, z=14, x=x, y=y)
        data = self._fetch(url, {"access_token": self.token}, None)
        return data.get("features", [])

    def nearest_image(
        self,
        lon: float,
        lat: float,
        *,
        radius_m: float = 30.0,
        exclude_pano: bool = True,
    ) -> Optional[MapillaryImage]:
        """Nearest usable image to a point: fetch tile, filter by radius + pano.

        Implements the spec's client-side spatial filter (no server query). By
        default excludes ``is_pano`` frames — pinhole geometry is invalid on them.
        """
        best: Optional[MapillaryImage] = None
        best_d = radius_m
        for feat in self.images_in_tile(lon, lat):
            props = feat.get("properties", feat)
            geom = feat.get("geometry", {})
            coords = geom.get("coordinates") if geom else [props.get("lon"), props.get("lat")]
            if not coords or coords[0] is None:
                continue
            img = MapillaryImage(
                image_id=str(props.get("id")),
                lon=coords[0], lat=coords[1],
                is_pano=bool(props.get("is_pano", False)),
                camera_parameters=props.get("camera_parameters"),
                compass_angle=props.get("compass_angle"),
                captured_at=props.get("captured_at"),
                quality_score=props.get("quality_score"),
            )
            if exclude_pano and img.is_pano:
                continue
            d = haversine_m(lon, lat, img.lon, img.lat)
            if d <= best_d:
                best, best_d = img, d
        return best
