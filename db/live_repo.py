"""Live per-city backend (no PostGIS): fetch REAL trees from city open-data
portals on demand and serve them from an in-memory cache.

Activated by ``LIVE_MODE=1``. When a viewport query lands near a configured
city (``center`` in ``ingest/sources.yaml``), we fetch a capped set of real
trees around that city from its portal (Socrata/ArcGIS), score them through the
normal pipeline, and cache them. Subsequent queries filter the cache by radius.

This makes "pick a city, see real trees near you" work without a database. For
production, ingest the same sources into PostGIS (see DEPLOY.md) — the serving
code path in ``db.repository`` is identical.
"""

from __future__ import annotations

import math
import os
import uuid

_CACHE: dict[str, list[dict]] = {}
_CITIES: list[dict] | None = None

# How much to pull per city on first touch, and the fetch radius around center.
CITY_CACHE_MAX = int(os.getenv("LIVE_CITY_MAX", "4000"))
CITY_FETCH_RADIUS_M = float(os.getenv("LIVE_FETCH_RADIUS_M", "9000"))
CITY_MATCH_MAX_M = 80_000.0        # a query must be within 80 km of a city center


def _haversine_m(lon1, lat1, lon2, lat2) -> float:
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp = math.radians(lat2 - lat1)
    dl = math.radians(lon2 - lon1)
    h = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * 6_371_000.0 * math.asin(min(1.0, math.sqrt(h)))


def _h3(lat, lon, res):
    try:
        import h3

        return h3.latlng_to_cell(lat, lon, res)
    except Exception:
        return None


def cities() -> list[dict]:
    """Configured cities that can be shown in the selector (have a center)."""
    global _CITIES
    if _CITIES is None:
        from ingest.run_ingest import load_sources

        out = []
        for s in load_sources():
            c = s.get("center")
            if c and s.get("country") in ("US", "CA"):
                out.append({
                    "source_id": s["source_id"],
                    "city": s.get("city", s["source_id"]),
                    "center": c,
                    "name": s.get("name", ""),
                })
        _CITIES = sorted(out, key=lambda x: x["city"])
    return _CITIES


def _source_by_id(source_id: str) -> dict | None:
    from ingest.run_ingest import load_sources

    for s in load_sources():
        if s["source_id"] == source_id:
            return s
    return None


def _nearest_city(lon: float, lat: float) -> dict | None:
    best, best_d = None, CITY_MATCH_MAX_M
    for c in cities():
        d = _haversine_m(lon, lat, c["center"][0], c["center"][1])
        if d <= best_d:
            best, best_d = c, d
    return best


def _ensure_city(source_id: str) -> list[dict]:
    """Fetch + score + cache real trees around a city's center (once)."""
    if source_id in _CACHE:
        return _CACHE[source_id]

    from ingest.fetcher import iter_source_records
    from ingest.pipeline import build_tree
    from ingest.dedup import dedup
    from ingest.run_ingest import today

    src = _source_by_id(source_id)
    if not src:
        _CACHE[source_id] = []
        return []

    lon, lat = src["center"]
    captured = today()
    rows: list[dict] = []
    try:
        for rec in iter_source_records(
            src, max_records=CITY_CACHE_MAX,
            near=(lon, lat, CITY_FETCH_RADIUS_M),
        ):
            tree = build_tree(rec, src, captured_at=captured)
            if tree:
                rows.append(tree)
    except Exception as exc:  # network/portal hiccup -> empty, not a crash
        print(f"[live] fetch failed for {source_id}: {exc}")
        _CACHE[source_id] = []
        return []

    rows = dedup(rows, meters=1.0)

    # Reconcile against live OSM (public/private gate + power-line hazard) so the
    # eligibility/hazard signals apply to live trees too. Best-effort: on any
    # Overpass failure this no-ops and trees keep their species+size score.
    if os.getenv("LIVE_RECONCILE", "1").lower() in ("1", "true", "yes"):
        try:
            from tierB.overpass import fetch_osm_context
            from tierB.run_reconcile import reconcile_tree

            recon_radius = float(os.getenv("LIVE_RECONCILE_RADIUS_M", "3500"))
            ctx = fetch_osm_context(lon, lat, recon_radius)
            if ctx.polygons or ctx.lines:
                rows = [reconcile_tree(t, ctx) for t in rows]
                print(f"[live] reconciled {source_id} against "
                      f"{len(ctx.polygons)} parcels / {len(ctx.lines)} power lines")
        except Exception as exc:
            print(f"[live] reconciliation skipped for {source_id}: {exc}")

    for t in rows:
        t.setdefault("tree_id", str(uuid.uuid4()))
        t["h3_r8"] = _h3(t["lat"], t["lon"], 8)
        t["h3_r10"] = _h3(t["lat"], t["lon"], 10)
        t.setdefault("eligible", True)
    _CACHE[source_id] = rows
    print(f"[live] cached {len(rows)} real trees for {source_id}")
    return rows


def migrate() -> None:  # no-op; nothing to migrate
    return None


def query_trees(*, lon, lat, radius_m=500.0, public_only=True, min_score=0.0, limit=500):
    city = _nearest_city(lon, lat)
    if not city:
        return []
    trees = _ensure_city(city["source_id"])
    out = []
    for t in trees:
        if public_only and not (t.get("public_flag", True) and t.get("eligible", True)):
            continue
        if (t.get("score") or 0) < min_score:
            continue
        d = _haversine_m(lon, lat, t["lon"], t["lat"])
        if d > radius_m:
            continue
        row = dict(t)
        row["dist_m"] = round(d, 1)
        out.append(row)
    out.sort(key=lambda r: (r.get("score") is None, -(r.get("score") or 0)))
    return out[:limit]


def aggregate_h3(*, lon, lat, radius_m, resolution="h3_r8"):
    city = _nearest_city(lon, lat)
    if not city:
        return []
    buckets: dict[str, list[dict]] = {}
    for t in _ensure_city(city["source_id"]):
        if _haversine_m(lon, lat, t["lon"], t["lat"]) > radius_m:
            continue
        cell = t.get(resolution)
        if cell:
            buckets.setdefault(cell, []).append(t)
    cells = []
    for cell, ts in buckets.items():
        scores = [x["score"] for x in ts if x.get("score") is not None]
        cells.append({"cell": cell, "n": len(ts),
                      "mean_score": (sum(scores) / len(scores)) if scores else None,
                      "mean_confidence": None})
    return cells


def insert_report(tree_id, kind, payload):
    return str(uuid.uuid4())
