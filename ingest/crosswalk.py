"""Per-source field crosswalk + unit conversions (spec §2, Path 1).

Ports OpenTrees' per-source ``conform`` mapping idea into a declarative config
(``sources.yaml``). Each source names which raw columns map to our normalised
fields, and which columns are in imperial units. This module applies that map to
one raw record and returns a partially-normalised dict (before ``cleanTree``).

Unit conversions kept faithful to spec:
  - DBH: inches -> cm   (x 2.54)
  - height: feet -> m   (/ 3.28084)
"""

from __future__ import annotations

from typing import Any, Optional

INCH_TO_CM = 2.54
FEET_TO_M = 1.0 / 3.28084


def in_to_cm(inches: Optional[float]) -> Optional[float]:
    return None if inches is None else round(inches * INCH_TO_CM, 2)


def ft_to_m(feet: Optional[float]) -> Optional[float]:
    return None if feet is None else round(feet * FEET_TO_M, 3)


def _to_float(v: Any) -> Optional[float]:
    """Parse to float. Does NOT reject negatives (coordinates are often < 0)."""
    if v is None or v == "":
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _measure_float(v: Any) -> Optional[float]:
    """Parse a physical measure, rejecting negatives and common junk sentinels."""
    f = _to_float(v)
    if f is None:
        return None
    if f < 0 or f in (9999, 99999, -9999):
        return None
    return f


def _get(record: dict, key: Optional[str]) -> Any:
    if not key:
        return None
    return record.get(key)


def _convert_measure(value: Optional[float], unit: Optional[str], kind: str) -> Optional[float]:
    """Convert a raw measure to metric based on declared unit.

    kind: "dbh" (cm target) or "height" (m target). Unit may be None/"cm"/"m"
    (already metric), "in"/"inch"/"inches", or "ft"/"feet".
    """
    if value is None:
        return None
    u = (unit or "").lower()
    if kind == "dbh":
        if u in ("in", "inch", "inches"):
            return in_to_cm(value)
        if u in ("mm",):
            return round(value / 10.0, 2)
        return round(value, 2)  # assume cm
    if kind == "height":
        if u in ("ft", "feet", "foot"):
            return ft_to_m(value)
        if u in ("cm",):
            return round(value / 100.0, 3)
        return round(value, 3)  # assume m
    return value


def apply_crosswalk(record: dict, source: dict) -> dict:
    """Map one raw source record to normalised fields (pre-cleanTree).

    ``source`` is one entry from sources.yaml with ``crosswalk`` (field map) and
    optional ``units`` blocks. Returns a dict with keys: scientific, common,
    genus, species, family, dbh_cm, height_m, crown_m, health, maturity, lon,
    lat, source_ref. Missing fields are None.
    """
    cw = source.get("crosswalk", {})
    units = source.get("units", {})

    dbh_raw = _measure_float(_get(record, cw.get("dbh")))
    height_raw = _measure_float(_get(record, cw.get("height")))
    crown_raw = _measure_float(_get(record, cw.get("crown")))

    return {
        "scientific": _get(record, cw.get("scientific")),
        "common": _get(record, cw.get("common")),
        "genus": _get(record, cw.get("genus")),
        "species": _get(record, cw.get("species")),
        "family": _get(record, cw.get("family")),
        "dbh_cm": _convert_measure(dbh_raw, units.get("dbh"), "dbh"),
        "height_m": _convert_measure(height_raw, units.get("height"), "height"),
        "crown_m": _convert_measure(crown_raw, units.get("crown"), "height"),
        "health": _get(record, cw.get("health")),
        "maturity": _get(record, cw.get("maturity")),
        "lon": _to_float(_get(record, cw.get("lon"))),
        "lat": _to_float(_get(record, cw.get("lat"))),
        "source_ref": _stringify(_get(record, cw.get("ref"))),
    }


def _stringify(v: Any) -> Optional[str]:
    if v is None or v == "":
        return None
    return str(v)
