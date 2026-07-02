"""CLI: apply Tier B reconciliation to scored trees (spec §4.2).

Given already-ingested Tier A trees and local OSM geometry, this:
  1. sets ``public_flag`` / ``eligible`` from land-use containment, and
  2. re-scores with the hazard penalty applied,
then reports the changes. Runs fully offline against the bundled samples:

    python -m tierB.run_reconcile \
        --trees data/sample_portland.geojson \
        --osm   data/sample_portland_osm.geojson

Aerial detection (finding NEW trees where no inventory exists) is a separate
step; see ``tierB.detect.detect_orthophoto`` (needs imagery + the tierb extra).
"""

from __future__ import annotations

import argparse
import json
from typing import Optional

from score.climbability import score_tree

from .parcels import EligibilityResult, OsmContext, assess_eligibility, context_from_geojson


def reconcile_tree(tree: dict, ctx: OsmContext) -> dict:
    """Return a copy of ``tree`` with Tier B gate + penalty applied.

    ``tree`` is a Tier A row (as produced by ``ingest.pipeline.build_tree``):
    it must carry ``lon``, ``lat`` and the scoring fields. The climbability
    score is recomputed through ``score_tree`` so the ``why_scored`` trace stays
    truthful about what changed.
    """
    assessment: EligibilityResult = assess_eligibility(
        tree["lon"], tree["lat"], ctx,
        incoming_public_flag=tree.get("public_flag"),
        detected=bool(tree.get("detected", False)),
    )
    scored = score_tree(
        genus=tree.get("genus"),
        species=tree.get("species"),
        family=tree.get("family"),
        dbh_cm=tree.get("dbh_cm"),
        height_m=tree.get("height_m"),
        captured_at_fresh=tree.get("provenance", {}).get("captured_at_fresh"),
        source_id=tree.get("source_id"),
        source_url=tree.get("provenance", {}).get("source_url"),
        license_=tree.get("provenance", {}).get("license"),
        tierb=assessment,
    )
    out = dict(tree)
    out.update(
        public_flag=assessment.public_flag,
        eligible=scored.eligible,
        score=scored.score,
        confidence=scored.confidence,
        why_scored=scored.why_scored,
        provenance=scored.provenance,
        hazards=[h.__dict__ for h in assessment.hazards],
        tierb_penalty=assessment.penalty,
    )
    return out


def _load_trees(path: str, source_id: str) -> list[dict]:
    """Load trees via the Tier A pipeline so we operate on scored rows."""
    from ingest.run_ingest import ingest_source, load_sources  # local import

    by_id = {s["source_id"]: s for s in load_sources()}
    if source_id not in by_id:
        raise SystemExit(f"unknown source: {source_id}")
    return ingest_source(by_id[source_id], sample_path=path)


def main(argv: Optional[list[str]] = None) -> int:
    ap = argparse.ArgumentParser(description="Tier B reconciliation (offline).")
    ap.add_argument("--trees", required=True, help="GeoJSON of Tier A trees")
    ap.add_argument("--osm", required=True, help="GeoJSON of OSM land-use + hazards")
    ap.add_argument("--source", default="portland_parks_trees", help="source_id for the crosswalk")
    args = ap.parse_args(argv)

    with open(args.osm, encoding="utf-8") as fh:
        ctx = context_from_geojson(json.load(fh))
    trees = _load_trees(args.trees, args.source)

    excluded = 0
    penalised = 0
    for t in trees:
        before = t.get("score")
        r = reconcile_tree(t, ctx)
        if not r["eligible"]:
            excluded += 1
            print(f"  EXCLUDED  {t.get('common') or t.get('genus')!r}: private parcel")
        elif r["tierb_penalty"] != 1.0:
            penalised += 1
            print(
                f"  PENALTY   {t.get('common') or t.get('genus')!r}: "
                f"{before} -> {r['score']} (×{r['tierb_penalty']}) "
                f"{[h['kind'] for h in r['hazards']]}"
            )
        else:
            print(f"  ok        {t.get('common') or t.get('genus')!r}: eligible, no hazard")

    print(
        f"\nReconciled {len(trees)} trees: "
        f"{excluded} excluded (private), {penalised} penalised (hazard)."
    )
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
