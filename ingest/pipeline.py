"""Pure transform: raw source record -> normalised, scored tree dict.

Kept separate from I/O (fetching, DB) so it is fully unit-testable. Sequence:
  1. apply_crosswalk  — map fields, convert units.
  2. clean_tree_name  — OpenTrees normalisation; may DROP the record.
  3. geometry         — resolve lon/lat (crosswalk field or injected _lon/_lat).
  4. score_tree       — Tier A climbability score + why_scored + provenance.
"""

from __future__ import annotations

from typing import Optional

from score.climbability import score_tree

from .clean_tree import clean_tree_name
from .crosswalk import apply_crosswalk


def build_tree(
    record: dict, source: dict, captured_at: Optional[str] = None
) -> Optional[dict]:
    """Transform one raw record into a normalised tree row, or None if dropped.

    ``captured_at`` should be the ingestion date (freshness stamp); callers pass
    it in because Date.now-style calls are avoided in the pure layer.
    """
    mapped = apply_crosswalk(record, source)

    cleaned = clean_tree_name(
        scientific=mapped.get("scientific"),
        genus=mapped.get("genus"),
        species=mapped.get("species"),
        common=mapped.get("common"),
    )
    if cleaned.dropped:
        return None  # vacant / stump / removed — not a tree

    # Geometry: prefer explicit crosswalk lon/lat, else geometry-injected _lon/_lat.
    lon = mapped.get("lon")
    lat = mapped.get("lat")
    if lon is None:
        lon = record.get("_lon")
    if lat is None:
        lat = record.get("_lat")
    if lon is None or lat is None:
        return None  # no location -> unusable
    try:
        lon = float(lon)
        lat = float(lat)
    except (TypeError, ValueError):
        return None

    # Freshness: live-portal pulls stamped today are considered fresh.
    fresh = source.get("path") == "live"

    scored = score_tree(
        genus=cleaned.genus,
        species=cleaned.species,
        family=mapped.get("family"),
        dbh_cm=mapped.get("dbh_cm"),
        height_m=mapped.get("height_m"),
        captured_at_fresh=fresh,
        source_id=source.get("source_id"),
        source_url=source.get("url"),
        license_=source.get("license"),
    )

    return {
        "source_id": source.get("source_id"),
        "source_ref": mapped.get("source_ref"),
        "scientific": cleaned.scientific,
        "genus": cleaned.genus,
        "species": cleaned.species,
        "common": mapped.get("common"),
        "dbh_cm": mapped.get("dbh_cm"),
        "height_m": mapped.get("height_m"),
        "crown_m": mapped.get("crown_m"),
        "health": mapped.get("health"),
        "maturity": mapped.get("maturity"),
        "public_flag": bool(source.get("public_default", True)),
        "captured_at": captured_at,
        "lon": lon,
        "lat": lat,
        "score": scored.score,
        "confidence": scored.confidence,
        "why_scored": scored.why_scored,
        "provenance": scored.provenance,
    }
