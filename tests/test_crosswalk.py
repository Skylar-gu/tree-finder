from ingest.crosswalk import apply_crosswalk, ft_to_m, in_to_cm


def test_unit_conversions():
    assert in_to_cm(10) == 25.4          # DBH inches -> cm x2.54
    assert abs(ft_to_m(10) - 3.048) < 1e-3  # feet -> m /3.28084
    assert in_to_cm(None) is None


def test_apply_crosswalk_maps_and_converts():
    source = {
        "crosswalk": {
            "scientific": "spc_latin",
            "common": "spc_common",
            "dbh": "tree_dbh",
            "lon": "longitude",
            "lat": "latitude",
            "ref": "tree_id",
        },
        "units": {"dbh": "in"},
    }
    rec = {
        "spc_latin": "Quercus rubra",
        "spc_common": "Red Oak",
        "tree_dbh": "10",
        "longitude": "-73.9",
        "latitude": "40.7",
        "tree_id": 42,
    }
    out = apply_crosswalk(rec, source)
    assert out["scientific"] == "Quercus rubra"
    assert out["dbh_cm"] == 25.4
    assert out["lon"] == -73.9
    assert out["source_ref"] == "42"


def test_sentinel_junk_becomes_none():
    source = {"crosswalk": {"dbh": "d"}, "units": {"dbh": "cm"}}
    assert apply_crosswalk({"d": "9999"}, source)["dbh_cm"] is None
    assert apply_crosswalk({"d": "-5"}, source)["dbh_cm"] is None
