"""Species photos from Wikipedia (no API key).

Given a tree's scientific/common name, fetch a representative photo of the
SPECIES from the Wikipedia REST summary endpoint. This is a species reference
image (what this kind of tree looks like), not a photo of the individual tree —
that would require the Mapillary street-imagery enrichment.

Results are cached in-process. Wikipedia asks for a descriptive User-Agent.
Content is CC-BY-SA; we surface the page link + credit for attribution.
"""

from __future__ import annotations

import math
import os
import urllib.parse
from typing import Optional

# --- Street View: a photo of the ACTUAL tree location (like Google Maps) -------
# Needs a Google Maps API key (GOOGLE_MAPS_API_KEY). The key never reaches the
# browser — the image is proxied through /api/tree_photo/image.
_SV_META = "https://maps.googleapis.com/maps/api/streetview/metadata"
_SV_IMAGE = "https://maps.googleapis.com/maps/api/streetview"


def _google_key() -> Optional[str]:
    return os.getenv("GOOGLE_MAPS_API_KEY") or None


def _bearing(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Compass bearing (deg) from point 1 -> point 2, so the camera faces the tree."""
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dl = math.radians(lon2 - lon1)
    y = math.sin(dl) * math.cos(p2)
    x = math.cos(p1) * math.sin(p2) - math.sin(p1) * math.cos(p2) * math.cos(dl)
    return (math.degrees(math.atan2(y, x)) + 360.0) % 360.0


def tree_photo_info(lat: float, lon: float, fetch=None) -> dict:
    """Is there a street-level photo of this exact spot, and which way to look?

    Uses the (free) Street View metadata endpoint so we never show a grey
    "no imagery" tile, and computes the heading from the nearest panorama toward
    the tree so the image actually faces it.
    """
    key = _google_key()
    if not key:
        return {"available": False, "provider": None,
                "reason": "no street-imagery provider configured (set GOOGLE_MAPS_API_KEY)"}
    try:
        params = {"location": f"{lat},{lon}", "key": key}
        if fetch is not None:
            meta = fetch(_SV_META, params)
        else:
            import requests

            meta = requests.get(_SV_META, params=params, timeout=12).json()
    except Exception as exc:
        return {"available": False, "provider": "google", "reason": str(exc)}

    if meta.get("status") != "OK":
        return {"available": False, "provider": "google",
                "reason": "no Street View imagery at this location"}
    ploc = meta.get("location") or {}
    heading = _bearing(ploc.get("lat", lat), ploc.get("lng", lon), lat, lon)
    return {
        "available": True,
        "provider": "google",
        "heading": round(heading, 1),
        "date": meta.get("date"),
        "attribution": "© Google — Street View",
    }


def streetview_image(lat: float, lon: float, heading: Optional[float] = None,
                     size: str = "640x400", fov: int = 80):
    """Fetch the Street View JPEG bytes for a location (key stays server-side).

    Returns ``(content_bytes, content_type)`` or ``None`` if unavailable.
    """
    key = _google_key()
    if not key:
        return None
    params = {"size": size, "location": f"{lat},{lon}", "fov": fov,
              "pitch": 10, "key": key, "return_error_code": "true"}
    if heading is not None:
        params["heading"] = heading
    try:
        import requests

        resp = requests.get(_SV_IMAGE, params=params, timeout=15)
        if resp.status_code != 200:
            return None
        return resp.content, resp.headers.get("Content-Type", "image/jpeg")
    except Exception:
        return None

_SUMMARY = "https://en.wikipedia.org/api/rest_v1/page/summary/{title}"
_UA = "climbable-trees/1.0 (species reference photos; contact via app)"

_cache: dict[str, dict] = {}


def _fetch_summary(title: str, fetch=None) -> Optional[dict]:
    """Return the Wikipedia summary JSON for a title, or None."""
    slug = urllib.parse.quote(title.strip().replace(" ", "_"))
    url = _SUMMARY.format(title=slug)
    try:
        if fetch is not None:
            return fetch(url)
        import requests

        resp = requests.get(url, headers={"User-Agent": _UA}, timeout=12)
        if resp.status_code != 200:
            return None
        return resp.json()
    except Exception:
        return None


def _photo_from_summary(data: dict) -> Optional[dict]:
    thumb = (data or {}).get("thumbnail") or {}
    src = thumb.get("source")
    if not src:
        return None
    page = ((data.get("content_urls") or {}).get("desktop") or {}).get("page")
    return {
        "image": src,
        "title": data.get("title"),
        "extract": data.get("description") or "",
        "source_url": page,
        "credit": "Wikipedia / Wikimedia Commons (CC BY-SA)",
    }


def species_photo(
    scientific: Optional[str] = None,
    common: Optional[str] = None,
    genus: Optional[str] = None,
    fetch=None,
) -> dict:
    """Best available species photo, trying scientific → common → genus.

    Returns ``{"image": None}`` when nothing is found (front-end shows a
    graceful placeholder). Cached by the (scientific, common, genus) key.
    """
    key = f"{scientific}|{common}|{genus}".lower()
    if key in _cache:
        return _cache[key]

    result = {"image": None}
    for name in (scientific, common, genus):
        if not name:
            continue
        data = _fetch_summary(name, fetch=fetch)
        photo = _photo_from_summary(data) if data else None
        if photo:
            photo["query"] = name
            result = photo
            break

    _cache[key] = result
    return result
