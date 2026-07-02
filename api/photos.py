"""Species photos from Wikipedia (no API key).

Given a tree's scientific/common name, fetch a representative photo of the
SPECIES from the Wikipedia REST summary endpoint. This is a species reference
image (what this kind of tree looks like), not a photo of the individual tree —
that would require the Mapillary street-imagery enrichment.

Results are cached in-process. Wikipedia asks for a descriptive User-Agent.
Content is CC-BY-SA; we surface the page link + credit for attribution.
"""

from __future__ import annotations

import urllib.parse
from typing import Optional

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
