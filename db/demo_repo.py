"""In-memory demo backend (no PostGIS).

Activated by ``DEMO_MODE=1``. It lets you launch and click around the real API +
MapLibre frontend without a database — it loads the bundled offline sample
through the actual Tier A ingest pipeline, applies Tier B reconciliation, and
answers radius / aggregate / report calls in pure Python.

It is a DEMO convenience, not the production path: no persistence, small sample,
naive linear scans. For real use run PostGIS (``docker compose up`` or a local
instance) so ``db.repository`` talks to the database.
"""

from __future__ import annotations

import math
import os
import uuid

_DATA = os.path.join(os.path.dirname(__file__), "..", "data")
_R = 6_371_000.0

_TREES: list[dict] | None = None
_REPORTS: list[dict] = []


def _haversine_m(lon1, lat1, lon2, lat2) -> float:
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp = math.radians(lat2 - lat1)
    dl = math.radians(lon2 - lon1)
    h = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * _R * math.asin(min(1.0, math.sqrt(h)))


def _h3(lat, lon, res):
    try:
        import h3

        return h3.latlng_to_cell(lat, lon, res)
    except Exception:
        return None


def _load() -> list[dict]:
    """Ingest the sample through the real pipeline + Tier B reconciliation."""
    from ingest.run_ingest import ingest_source, load_sources
    from tierB.parcels import context_from_geojson
    from tierB.run_reconcile import reconcile_tree
    import json

    by_id = {s["source_id"]: s for s in load_sources()}
    src = by_id["portland_parks_trees"]
    trees = ingest_source(src, sample_path=os.path.join(_DATA, "sample_portland.geojson"))

    osm_path = os.path.join(_DATA, "sample_portland_osm.geojson")
    if os.path.exists(osm_path):
        with open(osm_path, encoding="utf-8") as fh:
            ctx = context_from_geojson(json.load(fh))
        trees = [reconcile_tree(t, ctx) for t in trees]

    for t in trees:
        t.setdefault("tree_id", str(uuid.uuid4()))
        t["h3_r8"] = _h3(t["lat"], t["lon"], 8)
        t["h3_r10"] = _h3(t["lat"], t["lon"], 10)
        t.setdefault("eligible", True)
    return trees


def _trees() -> list[dict]:
    global _TREES
    if _TREES is None:
        _TREES = _load()
    return _TREES


def migrate() -> None:  # no-op in demo
    _trees()


def query_trees(*, lon, lat, radius_m=500.0, public_only=True, min_score=0.0, limit=500):
    out = []
    for t in _trees():
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
    buckets: dict[str, list[dict]] = {}
    for t in _trees():
        if _haversine_m(lon, lat, t["lon"], t["lat"]) > radius_m:
            continue
        cell = t.get(resolution)
        if cell:
            buckets.setdefault(cell, []).append(t)
    cells = []
    for cell, ts in buckets.items():
        scores = [x["score"] for x in ts if x.get("score") is not None]
        confs = [x["confidence"] for x in ts if x.get("confidence") is not None]
        cells.append({
            "cell": cell,
            "n": len(ts),
            "mean_score": sum(scores) / len(scores) if scores else None,
            "mean_confidence": sum(confs) / len(confs) if confs else None,
        })
    return cells


def insert_report(tree_id, kind, payload):
    rid = str(uuid.uuid4())
    _REPORTS.append({"report_id": rid, "tree_id": tree_id, "kind": kind, "payload": payload})
    return rid
