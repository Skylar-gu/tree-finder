"""Pure helpers to run reach-match against a stored tree row (no DB, testable)."""

from __future__ import annotations

from typing import Optional

from score.reach import ReachParams, reach_match


def _from_why(why_scored, feature: str, key: str, default=None):
    if not isinstance(why_scored, list):
        return default
    for entry in why_scored:
        if isinstance(entry, dict) and entry.get("feature") == feature:
            return entry.get(key, default)
    return default


def reach_for_tree(tree_row: dict, params: ReachParams) -> dict:
    """Run the reach-match for one stored tree using its persisted features.

    In v1 there is no branch data, so this always runs the form-based-guess
    degradation path. The inputs (scaffold_form, f_dbh, estimated) are read back
    out of the stored ``why_scored`` trace — features are NOT recomputed.
    """
    why = tree_row.get("why_scored")
    scaffold_form = _from_why(why, "species", "scaffold_form")
    f_dbh = _from_why(why, "dbh", "value")
    dbh_estimated = bool(_from_why(why, "dbh", "estimated", False))

    result = reach_match(
        params,
        branches=None,  # v1: no per-branch geometry anywhere
        scaffold_form=scaffold_form,
        f_dbh=f_dbh,
        dbh_estimated=dbh_estimated,
    )
    return result.to_dict()


def params_from_body(h: float, weight: float, delta: float, d_min: float, alpha: float) -> ReachParams:
    return ReachParams(
        h_m=h, weight_kg=weight, delta=delta, d_min_cm=d_min, alpha=alpha
    )
