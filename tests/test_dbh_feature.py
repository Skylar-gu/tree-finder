from features.dbh_feature import (
    SATURATION_CM,
    dbh_size_feature,
    estimate_dbh_from_height,
)


def test_monotone_increasing_below_saturation():
    a = dbh_size_feature(15).score
    b = dbh_size_feature(30).score
    c = dbh_size_feature(50).score
    assert a < b < c


def test_sapling_floor():
    assert dbh_size_feature(5).score <= 0.05


def test_saturation():
    assert dbh_size_feature(SATURATION_CM).score == 1.0
    assert dbh_size_feature(200).score == 1.0


def test_measured_basis():
    f = dbh_size_feature(40)
    assert f.basis == "measured"
    assert not f.estimated


def test_height_allometry_fallback_marked_estimated():
    f = dbh_size_feature(None, height_m=20, genus="Quercus")
    assert f.basis == "height_allometry"
    assert f.estimated
    assert f.dbh_cm_used is not None
    assert 0.0 <= f.score <= 1.0


def test_no_size_signal_returns_modest_non_zero():
    f = dbh_size_feature(None, None)
    assert f.basis == "none"
    assert 0.0 < f.score < 0.5


def test_estimate_dbh_from_height_positive():
    assert estimate_dbh_from_height(20, "Quercus") > 0
