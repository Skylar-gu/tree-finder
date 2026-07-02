from score.climbability import score_tree


def test_score_has_trace_confidence_provenance():
    r = score_tree(genus="Quercus", species="rubra", dbh_cm=40, captured_at_fresh=True)
    assert r.score is not None
    assert 0.0 <= r.score <= 1.0
    assert 0.0 <= r.confidence <= 0.75  # hard Tier-A ceiling
    assert any(w["feature"] == "_aggregate" for w in r.why_scored)
    assert "signals" in r.provenance
    assert "species_prior" in r.provenance["signals"]
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


def test_street_geometry_absent_without_measurement():
    r = score_tree(genus="Quercus", dbh_cm=40)
    agg = [w for w in r.why_scored if w["feature"] == "_aggregate"][0]
    assert agg["weights_used"]["w_streetcv"] == 0.0
    assert "street_geometry" not in r.provenance["signals"]


def test_street_geometry_signal_activates_weight():
    r = score_tree(genus="Quercus", dbh_cm=40, f_streetcv=0.8)
    agg = [w for w in r.why_scored if w["feature"] == "_aggregate"][0]
    assert agg["weights_used"]["w_streetcv"] > 0.0
    assert "street_geometry" in r.provenance["signals"]


def test_confidence_ceiling_never_certifies():
    # Even the best-case Tier-A tree stays well under certainty.
    r = score_tree(genus="Quercus", species="rubra", dbh_cm=55, captured_at_fresh=True)
    assert r.confidence <= 0.75
