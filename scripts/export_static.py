"""Export the live-mode demo cities to static JSON for GitHub Pages.

Fetches + scores real trees per configured US city (same code path as
LIVE_MODE serving) and writes ``docs/data/<source_id>.json`` plus a
``cities.json`` manifest. The static frontend in ``docs/`` filters by
radius and computes the reach-match form guess client-side, so no API
server is needed.

Run from the repo root:  python -m scripts.export_static
"""

from __future__ import annotations

import json
import pathlib
import sys

# Fields the static frontend needs; everything else is dropped to keep
# the per-city payload small. why_scored stays: it feeds the client-side
# reach-match (scaffold_form / f_dbh) and the "why scored" panel.
_KEEP = (
    "tree_id", "lat", "lon", "common", "scientific", "genus",
    "dbh_cm", "height_m", "score", "confidence", "eligible",
    "why_scored", "provenance", "hazards",
)


def _trim(t: dict) -> dict:
    out = {k: t[k] for k in _KEEP if t.get(k) is not None}
    out["lat"] = round(out["lat"], 6)
    out["lon"] = round(out["lon"], 6)
    return out


# Which cities the static demo exposes — well-known ones only. Sources stay in
# sources.yaml for the full app regardless.
DEMO_CITIES = {
    "nyc_street_trees_2015", "sf_street_trees", "denver_tree_inventory",
    "honolulu_exceptional_trees", "cambridge_street_trees",
    "boston_street_trees", "toronto_street_trees", "montreal_public_trees",
}


def _median_center(rows: list[dict]) -> list[float]:
    """Median lon/lat of the exported trees, so the selector lands on data
    (portal-side ordering/filters can pull a slice away from the yaml center)."""
    lons = sorted(t["lon"] for t in rows)
    lats = sorted(t["lat"] for t in rows)
    return [round(lons[len(lons) // 2], 5), round(lats[len(lats) // 2], 5)]


def main() -> int:
    from db import live_repo

    out_dir = pathlib.Path(__file__).resolve().parent.parent / "docs" / "data"
    out_dir.mkdir(parents=True, exist_ok=True)

    manifest = []
    for c in live_repo.cities():
        sid = c["source_id"]
        if sid not in DEMO_CITIES:
            continue
        rows = live_repo._ensure_city(sid)
        if not rows:
            print(f"[export] SKIP {sid}: no rows (portal down?)")
            continue
        trimmed = [_trim(t) for t in rows]
        path = out_dir / f"{sid}.json"
        path.write_text(json.dumps(trimmed, separators=(",", ":")))
        manifest.append({
            "source_id": sid,
            "city": c["city"],
            "center": _median_center(trimmed),
            "count": len(trimmed),
            "file": f"data/{sid}.json",
        })
        print(f"[export] {sid}: {len(trimmed)} trees -> {path.name} "
              f"({path.stat().st_size // 1024} KB)")

    (out_dir / "cities.json").write_text(json.dumps(manifest, indent=1))
    print(f"[export] wrote manifest with {len(manifest)} cities")
    return 0 if manifest else 1


if __name__ == "__main__":
    sys.exit(main())
