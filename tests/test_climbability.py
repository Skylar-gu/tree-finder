from score.climbability import score_tree


def test_score_has_trace_confidence_provenance():
    r = score_tree(genus="Quercus", species="rubra", dbh_cm=40, captured_at_fresh=True)
    assert r.score is not None
    assert 0.0 <= r.score <= 1.0
    assert 0.0 <= r.confidence <= 0.75  # hard Tier-A ceiling
    assert any(w["feature"] == "_aggregate" for w in r.why_scored)
    assert "tiers" in r.provenance
    assert "A:species_prior" in r.provenance["tiers"]
    assert "NOT a safety certification" in r.provenance["disclaimer"]


def test_unknown_genus_lowers_confidence_but_still_scores():
    known = score_tree(genus="Quercus", dbh_cm=40)
    unknown = score_tree(genus="Notreal", dbh_cm=40)
    assert unknown.score is not None            # still scored on DBH
    assert unknown.confidence < known.confidence  # but trusted less


def test_estimated_dbh_lowers_confidence():
    measured = score_tree(genus="Quercus", dbh_cm=40)
    estimated = score_tree(genus="Quercus", height_m=20)
    assert estimated.confidence < measured.confidence


def test_streetcv_dormant_in_v1():
    r = score_tree(genus="Quercus", dbh_cm=40)
    agg = [w for w in r.why_scored if w["feature"] == "_aggregate"][0]
    assert agg["weights_used"]["w_streetcv"] == 0.0
    assert "C:street_cv" not in r.provenance["tiers"]


def test_tier_c_seam_activates_weight():
    r = score_tree(genus="Quercus", dbh_cm=40, f_streetcv=0.8)
    agg = [w for w in r.why_scored if w["feature"] == "_aggregate"][0]
    assert agg["weights_used"]["w_streetcv"] > 0.0
    assert "C:street_cv" in r.provenance["tiers"]


def test_confidence_ceiling_never_certifies():
    # Even the best-case Tier-A tree stays well under certainty.
    r = score_tree(genus="Quercus", species="rubra", dbh_cm=55, captured_at_fresh=True)
    assert r.confidence <= 0.75
