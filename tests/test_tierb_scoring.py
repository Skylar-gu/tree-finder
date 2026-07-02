"""Tier B integration into the climbability score (gate + penalty only)."""

from score.climbability import score_tree
from tierB.parcels import LineFeature, OsmContext, PolygonFeature, assess_eligibility


def _square(cx, cy, half):
    return [[
        [cx - half, cy - half], [cx + half, cy - half],
        [cx + half, cy + half], [cx - half, cy + half], [cx - half, cy - half],
    ]]


def test_tierb_none_leaves_v1_behaviour_unchanged():
    a = score_tree(genus="Quercus", dbh_cm=60)
    b = score_tree(genus="Quercus", dbh_cm=60, tierb=None)
    assert a.score == b.score
    assert a.eligible is True
    assert "eligible" in a.to_dict()  # field always present


def test_private_parcel_marks_ineligible_but_keeps_trace():
    ctx = OsmContext(polygons=[
        PolygonFeature(tag=("landuse", "residential"), polygon=_square(-122.0, 45.0, 0.001)),
    ])
    tb = assess_eligibility(-122.0, 45.0, ctx, incoming_public_flag=True)
    res = score_tree(genus="Quercus", dbh_cm=55, tierb=tb)
    assert res.eligible is False
    assert res.provenance["eligible"] is False
    assert res.provenance["eligibility"]["excluded"] is True
    assert "eligibility" in res.provenance["signals"]


def test_hazard_penalty_lowers_score_but_adds_no_positive_signal():
    ctx = OsmContext(lines=[
        LineFeature(kind="power_line", line=[(-122.0, 45.0), (-122.0, 45.001)]),
    ])
    tb = assess_eligibility(-122.0 + 0.00005, 45.0005, ctx)
    base = score_tree(genus="Quercus", dbh_cm=55)
    pen = score_tree(genus="Quercus", dbh_cm=55, tierb=tb)
    assert pen.score < base.score              # penalised
    assert pen.eligible is True                # hazard != exclusion
    # Tier B contributes no positive term: penalty is multiplicative <= 1.
    assert pen.score <= base.score
    entry = next(w for w in pen.why_scored if w["feature"] == "_eligibility")
    assert entry["penalty"] < 1.0
    assert entry["score_after_penalty"] == pen.score


def test_tierb_penalty_is_clamped_and_ordered():
    # Two hazards compound multiplicatively, staying in [0,1].
    ctx = OsmContext(lines=[
        LineFeature(kind="power_line", line=[(-122.0, 45.0), (-122.0, 45.001)]),
        LineFeature(kind="highway", line=[(-122.001, 45.0005), (-122.0, 45.0005)]),
    ])
    tb = assess_eligibility(-122.0 + 0.00003, 45.0005, ctx)
    assert 0.0 <= tb.penalty <= 1.0
    res = score_tree(genus="Quercus", dbh_cm=55, tierb=tb)
    assert res.score is None or 0.0 <= res.score <= 1.0
