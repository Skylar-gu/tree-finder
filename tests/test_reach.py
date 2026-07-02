from score.reach import ReachParams, reach_match


def test_v1_default_is_form_based_guess_not_measured_ladder():
    r = reach_match(ReachParams(), scaffold_form=0.9, f_dbh=0.8)
    assert r.mode == "form_based_guess"
    assert r.is_measured_ladder is False
    assert r.ladder == []            # NEVER emit a fake ladder
    assert r.reachable_height_m is None
    assert r.plausibility is not None
    assert "FORM-BASED GUESS" in " ".join(r.notes)


def test_form_guess_confidence_is_low():
    r = reach_match(ReachParams(), scaffold_form=0.9, f_dbh=0.8)
    assert r.confidence <= 0.35


def test_no_signal_cannot_even_guess():
    r = reach_match(ReachParams(), scaffold_form=None, f_dbh=None)
    assert r.plausibility is None
    assert r.reachable is False


def test_weight_raises_effective_d_min():
    light = ReachParams(weight_kg=60).effective_d_min_cm
    heavy = ReachParams(weight_kg=110).effective_d_min_cm
    assert heavy > light  # section-modulus scaling


def test_measured_ladder_runs_only_with_branch_data():
    # future Tier C path: real branches -> a measured ladder
    branches = [(2.0, 15.0), (2.6, 12.0), (3.3, 11.0), (10.0, 20.0)]
    r = reach_match(ReachParams(h_m=1.8), branches=branches)
    assert r.mode == "measured_ladder"
    assert r.is_measured_ladder is True
    assert r.reachable is True
    # ladder breaks before the far 10 m branch
    assert r.reachable_height_m is not None
    assert r.reachable_height_m < 10.0


def test_measured_mount_fails_when_lowest_branch_too_high():
    branches = [(6.0, 20.0), (6.5, 18.0)]
    r = reach_match(ReachParams(h_m=1.7), branches=branches)
    assert r.reachable is False


def test_thin_branches_excluded_by_d_min():
    branches = [(2.0, 3.0), (2.5, 4.0)]  # all below d_min
    r = reach_match(ReachParams(), branches=branches)
    assert r.reachable is False


def test_constants_are_tunable():
    p = ReachParams(alpha=1.25, delta=0.7, d_min_cm=12)
    assert p.ground_reach_m == 1.25 * p.h_m
    assert p.allowed_gap_m() > 0
