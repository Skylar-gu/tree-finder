"""Portal fetchers (spec §2 Path 1 batch + Path 2 live).

Reads download/query URLs from sources.yaml and yields raw records (plain
dicts). Geometry-bearing portals (ArcGIS, GeoJSON) inject ``_lon``/``_lat`` keys
so the crosswalk / caller can find coordinates uniformly.

Portals supported:
  - socrata : SoQL JSON endpoint, paged via $limit/$offset (Path 2 live).
  - arcgis  : Feature Service layer, /query paged via resultOffset -> geojson.
  - ckan    : datastore_search paged via offset.
  - geojson : single GeoJSON file (batch snapshot).

Network access is optional: pass ``session=`` a stub in tests, or use
``iter_records_from_geojson`` on a local file. Nothing here requires a live
network at import time.
"""

from __future__ import annotations

from typing import Iterable, Iterator, Optional

try:  # requests is optional at import time (tests may not need the network)
    import requests
except Exception:  # pragma: no cover
    requests = None  # type: ignore

DEFAULT_PAGE = 1000
DEFAULT_TIMEOUT = 60


def _session(session=None):
    if session is not None:
        return session
    if requests is None:  # pragma: no cover
        raise RuntimeError("requests not installed and no session provided")
    return requests.Session()


# ----------------------------------------------------------------- Socrata
def iter_records_socrata(
    url: str,
    *,
    where: Optional[str] = None,
    page: int = DEFAULT_PAGE,
    max_records: Optional[int] = None,
    session=None,
) -> Iterator[dict]:
    """Page a Socrata JSON endpoint with $limit/$offset (SoQL $where filter)."""
    s = _session(session)
    offset = 0
    fetched = 0
    while True:
        params = {"$limit": page, "$offset": offset, "$order": ":id"}
        if where:
            params["$where"] = where
        resp = s.get(url, params=params, timeout=DEFAULT_TIMEOUT)
        resp.raise_for_status()
        rows = resp.json()
        if not rows:
            break
        for row in rows:
            yield row
            fetched += 1
            if max_records and fetched >= max_records:
                return
        if len(rows) < page:
            break
        offset += page


# ------------------------------------------------------------------ ArcGIS
def iter_records_arcgis(
    layer_url: str,
    *,
    where: str = "1=1",
    page: int = DEFAULT_PAGE,
    max_records: Optional[int] = None,
    session=None,
) -> Iterator[dict]:
    """Page an ArcGIS Feature Service layer as GeoJSON.

    Emits property dicts with ``_lon``/``_lat`` injected from point geometry.
    """
    s = _session(session)
    query_url = layer_url.rstrip("/") + "/query"
    offset = 0
    fetched = 0
    while True:
        params = {
            "where": where,
            "outFields": "*",
            "f": "geojson",
            "resultOffset": offset,
            "resultRecordCount": page,
            "outSR": 4326,
        }
        resp = s.get(query_url, params=params, timeout=DEFAULT_TIMEOUT)
        resp.raise_for_status()
        gj = resp.json()
        feats = gj.get("features", [])
        if not feats:
            break
        for feat in feats:
            yield _geojson_feature_to_record(feat)
            fetched += 1
            if max_records and fetched >= max_records:
                return
        if len(feats) < page or not gj.get("exceededTransferLimit", False):
            # Some services omit exceededTransferLimit; the len check is the
            # reliable stop condition.
            if len(feats) < page:
                break
        offset += page


# -------------------------------------------------------------------- CKAN
def iter_records_ckan(
    base_url: str,
    resource_id: str,
    *,
    page: int = DEFAULT_PAGE,
    max_records: Optional[int] = None,
    session=None,
) -> Iterator[dict]:
    """Page a CKAN datastore_search resource."""
    s = _session(session)
    endpoint = base_url.rstrip("/") + "/api/3/action/datastore_search"
    offset = 0
    fetched = 0
    while True:
        params = {"resource_id": resource_id, "limit": page, "offset": offset}
        resp = s.get(endpoint, params=params, timeout=DEFAULT_TIMEOUT)
        resp.raise_for_status()
        result = resp.json().get("result", {})
        records = result.get("records", [])
        if not records:
            break
        for rec in records:
            yield rec
            fetched += 1
            if max_records and fetched >= max_records:
                return
        if len(records) < page:
            break
        offset += page


# ----------------------------------------------------------------- GeoJSON
def iter_records_from_geojson(path_or_obj) -> Iterator[dict]:
    """Yield property dicts (with _lon/_lat) from a GeoJSON file path or object."""
    import json

    if isinstance(path_or_obj, (str, bytes)):
        with open(path_or_obj, "r", encoding="utf-8") as fh:
            gj = json.load(fh)
    else:
        gj = path_or_obj
    for feat in gj.get("features", []):
        yield _geojson_feature_to_record(feat)


def _geojson_feature_to_record(feat: dict) -> dict:
    props = dict(feat.get("properties") or {})
    geom = feat.get("geometry") or {}
    if geom.get("type") == "Point":
        coords = geom.get("coordinates") or [None, None]
        props["_lon"] = coords[0]
        props["_lat"] = coords[1]
    return props


# ----------------------------------------------------- dispatch by source cfg
def iter_source_records(
    source: dict, *, max_records: Optional[int] = None, session=None
) -> Iterable[dict]:
    """Dispatch to the right fetcher based on a sources.yaml entry."""
    portal = source.get("portal")
    url = source.get("url")
    where = source.get("where")
    if portal == "socrata":
        return iter_records_socrata(
            url, where=where, max_records=max_records, session=session
        )
    if portal == "arcgis":
        return iter_records_arcgis(
            url, where=where or "1=1", max_records=max_records, session=session
        )
    if portal == "ckan":
        return iter_records_ckan(
            source["url"],
            source["resource_id"],
            max_records=max_records,
            session=session,
        )
    if portal == "geojson":
        return iter_records_from_geojson(url)
    raise ValueError(f"unknown portal type: {portal!r}")
