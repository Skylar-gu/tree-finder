"""PostGIS reads/writes: migrate, upsert trees, viewport/radius query, reports.

The API layer calls ``query_trees`` for a viewport/radius and then runs the
reach-match per request in Python (spec §8: reach-match server-side, no feature
recompute). H3 buckets are computed here on write for aggregation.
"""

from __future__ import annotations

import json
import os
from typing import Optional

from .connection import get_conn

MIGRATIONS_DIR = os.path.join(os.path.dirname(__file__), "migrations")

# DB-free backends (no PostGIS). Production path is unaffected when both unset.
#   LIVE_MODE=1 -> fetch REAL trees per city from open-data portals (live_repo)
#   DEMO_MODE=1 -> serve the tiny bundled offline sample        (demo_repo)
_LIVE = os.getenv("LIVE_MODE", "").lower() in ("1", "true", "yes")
_DEMO = os.getenv("DEMO_MODE", "").lower() in ("1", "true", "yes")


def _backend():
    """Return the active DB-free backend module, or None for real PostGIS."""
    if _LIVE:
        from . import live_repo

        return live_repo
    if _DEMO:
        from . import demo_repo

        return demo_repo
    return None


def _h3(lat: float, lon: float, res: int) -> Optional[str]:
    try:
        import h3

        return h3.latlng_to_cell(lat, lon, res)
    except Exception:
        return None


def migrate() -> None:
    """Apply all *.sql migrations in order (idempotent)."""
    b = _backend()
    if b:
        return b.migrate()
    files = sorted(f for f in os.listdir(MIGRATIONS_DIR) if f.endswith(".sql"))
    with get_conn() as conn:
        with conn.cursor() as cur:
            for f in files:
                with open(os.path.join(MIGRATIONS_DIR, f), "r", encoding="utf-8") as fh:
                    cur.execute(fh.read())
        conn.commit()


def upsert_trees(rows: list[dict]) -> int:
    """Insert/update normalised tree rows (from ingest.pipeline.build_tree).

    Upsert key is (source_id, source_ref) — the exact-dedup guard. Returns the
    number of rows written.
    """
    if not rows:
        return 0
    sql = """
        INSERT INTO trees (
            geom, source_id, source_ref, scientific, genus, species, common,
            dbh_cm, height_m, crown_m, health, maturity, public_flag,
            captured_at, score, confidence, why_scored, provenance, h3_r8, h3_r10,
            detected, eligible, hazards, tierb_penalty
        ) VALUES (
            ST_SetSRID(ST_MakePoint(%(lon)s, %(lat)s), 4326),
            %(source_id)s, %(source_ref)s, %(scientific)s, %(genus)s, %(species)s,
            %(common)s, %(dbh_cm)s, %(height_m)s, %(crown_m)s, %(health)s,
            %(maturity)s, %(public_flag)s, %(captured_at)s, %(score)s,
            %(confidence)s, %(why_scored)s, %(provenance)s, %(h3_r8)s, %(h3_r10)s,
            %(detected)s, %(eligible)s, %(hazards)s, %(tierb_penalty)s
        )
        ON CONFLICT (source_id, source_ref) WHERE source_ref IS NOT NULL
        DO UPDATE SET
            geom = EXCLUDED.geom, scientific = EXCLUDED.scientific,
            genus = EXCLUDED.genus, species = EXCLUDED.species,
            common = EXCLUDED.common, dbh_cm = EXCLUDED.dbh_cm,
            height_m = EXCLUDED.height_m, crown_m = EXCLUDED.crown_m,
            health = EXCLUDED.health, maturity = EXCLUDED.maturity,
            public_flag = EXCLUDED.public_flag, captured_at = EXCLUDED.captured_at,
            score = EXCLUDED.score, confidence = EXCLUDED.confidence,
            why_scored = EXCLUDED.why_scored, provenance = EXCLUDED.provenance,
            h3_r8 = EXCLUDED.h3_r8, h3_r10 = EXCLUDED.h3_r10,
            detected = EXCLUDED.detected, eligible = EXCLUDED.eligible,
            hazards = EXCLUDED.hazards, tierb_penalty = EXCLUDED.tierb_penalty,
            ingested_at = now();
    """
    n = 0
    with get_conn() as conn:
        with conn.cursor() as cur:
            for r in rows:
                params = dict(r)
                params["why_scored"] = json.dumps(r.get("why_scored"))
                params["provenance"] = json.dumps(r.get("provenance"))
                params["h3_r8"] = _h3(r["lat"], r["lon"], 8)
                params["h3_r10"] = _h3(r["lat"], r["lon"], 10)
                # Tier B columns: default to v1 semantics when absent.
                params["detected"] = bool(r.get("detected", False))
                params["eligible"] = bool(r.get("eligible", True))
                params["hazards"] = json.dumps(r.get("hazards")) if r.get("hazards") is not None else None
                params["tierb_penalty"] = r.get("tierb_penalty")
                cur.execute(sql, params)
                n += 1
        conn.commit()
    return n


def query_trees(
    *,
    lon: float,
    lat: float,
    radius_m: float = 500.0,
    public_only: bool = True,
    min_score: float = 0.0,
    limit: int = 500,
) -> list[dict]:
    """Radius query returning stored trees + features needed for reach-match.

    Uses the GiST index via ST_DWithin (geography cast for metric distance).
    Public/eligible gate (invariant #3) is applied here.
    """
    b = _backend()
    if b:
        return b.query_trees(
            lon=lon, lat=lat, radius_m=radius_m,
            public_only=public_only, min_score=min_score, limit=limit,
        )
    where = ["ST_DWithin(geom::geography, ST_SetSRID(ST_MakePoint(%(lon)s,%(lat)s),4326)::geography, %(radius)s)"]
    if public_only:
        # Invariant #3: serve only public AND Tier-B-eligible trees (private
        # parcels reconciled by Tier B set eligible=false).
        where.append("public_flag = true")
        where.append("eligible = true")
    where.append("COALESCE(score, 0) >= %(min_score)s")
    sql = f"""
        SELECT tree_id, ST_X(geom) AS lon, ST_Y(geom) AS lat,
               source_id, source_ref, scientific, genus, species, common,
               dbh_cm, height_m, crown_m, health, maturity, public_flag,
               captured_at, score, confidence, why_scored, provenance,
               detected, eligible, hazards, tierb_penalty,
               ST_Distance(geom::geography,
                           ST_SetSRID(ST_MakePoint(%(lon)s,%(lat)s),4326)::geography) AS dist_m
        FROM trees
        WHERE {' AND '.join(where)}
        ORDER BY score DESC NULLS LAST
        LIMIT %(limit)s;
    """
    params = {
        "lon": lon,
        "lat": lat,
        "radius": radius_m,
        "min_score": min_score,
        "limit": limit,
    }
    out: list[dict] = []
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(sql, params)
            cols = [d[0] for d in cur.description]
            for row in cur.fetchall():
                out.append(dict(zip(cols, row)))
    return out


def aggregate_h3(
    *, lon: float, lat: float, radius_m: float, resolution: str = "h3_r8"
) -> list[dict]:
    """Aggregate tree counts + mean score per H3 cell in a radius (viewport zoom-out)."""
    if resolution not in ("h3_r8", "h3_r10"):
        raise ValueError("resolution must be h3_r8 or h3_r10")
    b = _backend()
    if b:
        return b.aggregate_h3(
            lon=lon, lat=lat, radius_m=radius_m, resolution=resolution
        )
    sql = f"""
        SELECT {resolution} AS cell, count(*) AS n,
               avg(score) AS mean_score, avg(confidence) AS mean_confidence
        FROM trees
        WHERE ST_DWithin(geom::geography,
              ST_SetSRID(ST_MakePoint(%(lon)s,%(lat)s),4326)::geography, %(radius)s)
          AND {resolution} IS NOT NULL
        GROUP BY {resolution};
    """
    out: list[dict] = []
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(sql, {"lon": lon, "lat": lat, "radius": radius_m})
            cols = [d[0] for d in cur.description]
            for row in cur.fetchall():
                out.append(dict(zip(cols, row)))
    return out


def insert_report(tree_id: Optional[str], kind: str, payload: dict) -> str:
    """Insert a correction/takedown/label report; returns report_id."""
    b = _backend()
    if b:
        return b.insert_report(tree_id, kind, payload)
    sql = """
        INSERT INTO reports (tree_id, kind, payload)
        VALUES (%s, %s, %s) RETURNING report_id;
    """
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(sql, (tree_id, kind, json.dumps(payload)))
            rid = cur.fetchone()[0]
        conn.commit()
    return str(rid)
