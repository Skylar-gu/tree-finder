"""Deduplication (spec §2).

Two stages, in order:
  1. Exact dedup on ``(source_id, source_ref)`` — the same portal row seen twice.
  2. Spatial dedup at ~1 m — the same physical tree published by overlapping
     sources. We snap coordinates to a grid whose cell is ~1 m at the given
     latitude and keep the first (or highest-confidence) record per cell.

This is a lightweight in-memory pass suitable for the modest per-city volumes
we ingest at a time. At scale it would move into PostGIS (ST_DWithin / cluster),
which is why the DB also carries the geometry + GiST index.
"""

from __future__ import annotations

import math
from typing import Iterable, Iterator

# ~1 m in degrees latitude (constant); longitude scaled by cos(lat).
_M_PER_DEG_LAT = 111_320.0


def _cell_key(lon: float, lat: float, meters: float) -> tuple[int, int]:
    deg_lat = meters / _M_PER_DEG_LAT
    deg_lon = meters / (_M_PER_DEG_LAT * max(math.cos(math.radians(lat)), 1e-6))
    return (round(lat / deg_lat), round(lon / deg_lon))


def dedup_exact(records: Iterable[dict]) -> Iterator[dict]:
    """Drop later records sharing (source_id, source_ref) with an earlier one."""
    seen: set[tuple] = set()
    for r in records:
        key = (r.get("source_id"), r.get("source_ref"))
        # Records with no source_ref cannot be exact-deduped; pass them through.
        if key[1] is None:
            yield r
            continue
        if key in seen:
            continue
        seen.add(key)
        yield r


def dedup_spatial(records: Iterable[dict], meters: float = 1.0) -> list[dict]:
    """Collapse cross-source near-duplicates within ``meters`` (~1 m default).

    Keeps the record with the higher ``confidence`` when two fall in the same
    cell (falls back to first-seen when confidence is absent/equal).
    """
    best: dict[tuple[int, int], dict] = {}
    for r in records:
        lon, lat = r.get("lon"), r.get("lat")
        if lon is None or lat is None:
            # No geometry -> cannot spatially dedup; keep under a unique key.
            best[(id(r), 0)] = r
            continue
        key = _cell_key(lon, lat, meters)
        if key not in best:
            best[key] = r
        else:
            incumbent = best[key]
            if (r.get("confidence") or 0) > (incumbent.get("confidence") or 0):
                best[key] = r
    return list(best.values())


def dedup(records: Iterable[dict], meters: float = 1.0) -> list[dict]:
    """Full pipeline: exact dedup then spatial dedup."""
    return dedup_spatial(dedup_exact(records), meters=meters)
