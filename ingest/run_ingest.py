"""Ingestion CLI: fetch -> crosswalk -> cleanTree -> score -> dedup -> store.

Usage:
    python -m ingest.run_ingest --list
    python -m ingest.run_ingest --source nyc_street_trees_2015 --max 2000
    python -m ingest.run_ingest --all --max 1000 --out data/trees.json   # dry run
    python -m ingest.run_ingest --source sf_street_trees --to-db

By default writes to a JSON file (dry run, no network to DB). --to-db upserts
into PostGIS via db.repository. --sample loads bundled offline fixtures so the
whole pipeline can be exercised without any network.
"""

from __future__ import annotations

import argparse
import datetime as _dt
import json
import os
import sys

import yaml

from .dedup import dedup
from .fetcher import iter_records_from_geojson, iter_source_records
from .pipeline import build_tree

SOURCES_PATH = os.path.join(os.path.dirname(__file__), "sources.yaml")


def load_sources() -> list[dict]:
    with open(SOURCES_PATH, "r", encoding="utf-8") as fh:
        return yaml.safe_load(fh).get("sources", [])


def today() -> str:
    return _dt.date.today().isoformat()


def ingest_source(
    source: dict, *, max_records=None, sample_path=None, session=None
) -> list[dict]:
    """Fetch + normalise + score one source. Returns deduped tree rows."""
    captured = today()
    if sample_path:
        raw = iter_records_from_geojson(sample_path)
    else:
        raw = iter_source_records(source, max_records=max_records, session=session)

    trees: list[dict] = []
    for rec in raw:
        tree = build_tree(rec, source, captured_at=captured)
        if tree is not None:
            trees.append(tree)
    return dedup(trees, meters=1.0)


def _reconcile_rows(rows: list[dict], source: dict, radius_m: float) -> list[dict]:
    """Reconcile ingested rows against live OSM (eligibility gate + hazards).

    Fetches OSM once around the city center; applies the public/private gate and
    power-line hazard penalty to every tree. Best-effort — Overpass failure
    leaves rows untouched.
    """
    try:
        from tierB.overpass import fetch_osm_context
        from tierB.run_reconcile import reconcile_tree

        lon, lat = source["center"]
        ctx = fetch_osm_context(lon, lat, radius_m)
        if not (ctx.polygons or ctx.lines):
            return rows
        print(f"[ingest] reconciling {source['source_id']} against "
              f"{len(ctx.polygons)} parcels / {len(ctx.lines)} power lines", file=sys.stderr)
        return [reconcile_tree(t, ctx) for t in rows]
    except Exception as e:
        print(f"[ingest] reconcile skipped for {source['source_id']}: {e}", file=sys.stderr)
        return rows


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description="Climbable-Trees ingestion")
    p.add_argument("--list", action="store_true", help="list configured sources")
    p.add_argument("--source", help="source_id to ingest")
    p.add_argument("--all", action="store_true", help="ingest every source")
    p.add_argument("--max", type=int, default=None, help="max records per source")
    p.add_argument("--sample", help="local GeoJSON fixture to ingest instead of network")
    p.add_argument("--out", default="data/trees.json", help="dry-run output JSON path")
    p.add_argument("--to-db", action="store_true", help="upsert into PostGIS")
    p.add_argument("--reconcile", action="store_true",
                   help="reconcile against live OSM (public/private gate + hazards)")
    p.add_argument("--reconcile-radius", type=float, default=25000.0,
                   help="OSM fetch radius (m) around each city center for --reconcile")
    args = p.parse_args(argv)

    sources = load_sources()
    by_id = {s["source_id"]: s for s in sources}

    if args.list:
        for s in sources:
            print(f"{s['source_id']:32s} {s.get('portal'):8s} {s.get('path'):6s} {s.get('name')}")
        return 0

    targets: list[dict]
    if args.all:
        targets = sources
    elif args.source:
        if args.source not in by_id:
            print(f"unknown source: {args.source}", file=sys.stderr)
            return 2
        targets = [by_id[args.source]]
    else:
        p.print_help()
        return 2

    all_rows: list[dict] = []
    for src in targets:
        print(f"[ingest] {src['source_id']} ...", file=sys.stderr)
        try:
            rows = ingest_source(src, max_records=args.max, sample_path=args.sample)
        except Exception as e:  # network / portal errors shouldn't abort the batch
            print(f"[ingest] {src['source_id']} FAILED: {e}", file=sys.stderr)
            continue
        if args.reconcile and src.get("center"):
            rows = _reconcile_rows(rows, src, args.reconcile_radius)
        print(f"[ingest] {src['source_id']}: {len(rows)} trees", file=sys.stderr)
        all_rows.extend(rows)

    if args.to_db:
        from db.repository import upsert_trees

        n = upsert_trees(all_rows)
        print(f"[ingest] upserted {n} rows into PostGIS", file=sys.stderr)
    else:
        os.makedirs(os.path.dirname(args.out) or ".", exist_ok=True)
        with open(args.out, "w", encoding="utf-8") as fh:
            json.dump(all_rows, fh, indent=2, default=str)
        print(f"[ingest] wrote {len(all_rows)} trees -> {args.out}", file=sys.stderr)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
