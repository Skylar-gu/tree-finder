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


def _inject_socrata_coords(row: dict, geo_field: Optional[str]) -> dict:
    """Inject ``_lon``/``_lat`` from a Socrata point column when present.

    Handles the two common shapes: a GeoJSON-ish point ``{"type":"Point",
    "coordinates":[lon,lat]}`` (``the_geom``/``location``) and a Socrata
    location object ``{"latitude":..,"longitude":..}``. Plain numeric
    latitude/longitude columns are left to the crosswalk.
    """
    if not geo_field or geo_field not in row:
        return row
    val = row[geo_field]
    if isinstance(val, dict):
        if val.get("type") == "Point" and val.get("coordinates"):
            lon, lat = val["coordinates"][0], val["coordinates"][1]
            row["_lon"], row["_lat"] = lon, lat
        elif "longitude" in val and "latitude" in val:
            row["_lon"], row["_lat"] = val.get("longitude"), val.get("latitude")
    return row


def socrata_within_circle(geo_field: str, lat: float, lon: float, radius_m: float) -> str:
    """SoQL ``within_circle`` clause for a point column (metres)."""
    return f"within_circle({geo_field}, {lat}, {lon}, {radius_m})"


def socrata_bbox(lat: float, lon: float, radius_m: float,
                 lat_field: str = "latitude", lon_field: str = "longitude") -> str:
    """Bounding-box clause on numeric lat/long columns (~radius_m half-extent)."""
    dlat = radius_m / 111_320.0
    import math
    dlon = radius_m / (111_320.0 * max(math.cos(math.radians(lat)), 1e-6))
    return (f"{lat_field} > {lat - dlat} AND {lat_field} < {lat + dlat} AND "
            f"{lon_field} > {lon - dlon} AND {lon_field} < {lon + dlon}")


# ----------------------------------------------------------------- Socrata
def iter_records_socrata(
    url: str,
    *,
    where: Optional[str] = None,
    page: int = DEFAULT_PAGE,
    max_records: Optional[int] = None,
    geo_field: Optional[str] = None,
    session=None,
) -> Iterator[dict]:
    """Page a Socrata JSON endpoint with $limit/$offset (SoQL $where filter).

    ``geo_field`` (e.g. ``the_geom``/``location``) is a point column whose
    coordinates are injected as ``_lon``/``_lat`` for datasets without plain
    latitude/longitude columns.
    """
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
            yield _inject_socrata_coords(row, geo_field)
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
def _inject_ckan_geometry(rec: dict) -> dict:
    """Inject ``_lon``/``_lat`` when a CKAN row carries a GeoJSON point.

    Some datastores (e.g. Toronto) store geometry as a JSON *string* column.
    """
    geom = rec.get("geometry")
    if isinstance(geom, str) and geom.lstrip().startswith("{"):
        import json

        try:
            geom = json.loads(geom)
        except ValueError:
            return rec
    if isinstance(geom, dict) and geom.get("type") == "Point":
        coords = geom.get("coordinates") or [None, None]
        rec["_lon"], rec["_lat"] = coords[0], coords[1]
    return rec


def iter_records_ckan(
    base_url: str,
    resource_id: str,
    *,
    filters: Optional[dict] = None,
    page: int = DEFAULT_PAGE,
    max_records: Optional[int] = None,
    session=None,
) -> Iterator[dict]:
    """Page a CKAN datastore_search resource.

    ``filters`` is CKAN's exact-match filter dict (JSON-encoded on the wire) —
    used to scope huge citywide datastores to one ward/borough.
    """
    import json

    s = _session(session)
    endpoint = base_url.rstrip("/") + "/api/3/action/datastore_search"
    offset = 0
    fetched = 0
    while True:
        params = {"resource_id": resource_id, "limit": page, "offset": offset}
        if filters:
            params["filters"] = json.dumps(filters)
        # Some datastores (Toronto) time out on cold pages; retry before giving up.
        resp = None
        for attempt in (1, 2, 3):
            try:
                resp = s.get(endpoint, params=params, timeout=DEFAULT_TIMEOUT * attempt)
                break
            except Exception:
                if attempt == 3:
                    raise
        resp.raise_for_status()
        result = resp.json().get("result", {})
        records = result.get("records", [])
        if not records:
            break
        for rec in records:
            yield _inject_ckan_geometry(rec)
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
    source: dict,
    *,
    max_records: Optional[int] = None,
    near: Optional[tuple] = None,
    session=None,
) -> Iterable[dict]:
    """Dispatch to the right fetcher based on a sources.yaml entry.

    ``near`` = (lon, lat, radius_m) adds a portal-side spatial filter so live
    per-city queries fetch only trees around a point.
    """
    portal = source.get("portal")
    url = source.get("url")
    where = source.get("where")
    geo_field = source.get("geo_field")
    if portal == "socrata":
        if near is not None:
            lon, lat, radius_m = near
            if geo_field:
                spatial = socrata_within_circle(geo_field, lat, lon, radius_m)
            else:
                spatial = socrata_bbox(lat, lon, radius_m)
            where = f"({where}) AND {spatial}" if where else spatial
        return iter_records_socrata(
            url, where=where, max_records=max_records,
            geo_field=geo_field, session=session,
        )
    if portal == "arcgis":
        # ArcGIS layers here are small enough to cap with max_records; the live
        # repo applies the radius filter client-side after fetch.
        return iter_records_arcgis(
            url, where=where or "1=1", max_records=max_records, session=session
        )
    if portal == "ckan":
        return iter_records_ckan(
            source["url"],
            source["resource_id"],
            filters=source.get("filters"),
            max_records=max_records,
            session=session,
        )
    if portal == "geojson":
        return iter_records_from_geojson(url)
    raise ValueError(f"unknown portal type: {portal!r}")
