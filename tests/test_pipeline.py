import os

from ingest.pipeline import build_tree
from ingest.run_ingest import ingest_source, load_sources

SAMPLE = os.path.join(os.path.dirname(__file__), "..", "data", "sample_portland.geojson")


def _portland_source():
    return {s["source_id"]: s for s in load_sources()}["portland_parks_trees"]


def test_build_tree_from_arcgis_style_record():
    src = _portland_source()
    rec = {
        "OBJECTID": 99,
        "Genus_species": "Quercus rubra",
        "Genus": "Quercus",
        "Species": "rubra",
        "DBH": 28.0,       # inches
        "HEIGHT": 55.0,    # feet
        "_lon": -122.6,
        "_lat": 45.5,
    }
    tree = build_tree(rec, src, captured_at="2026-07-02")
    assert tree["genus"] == "Quercus"
    assert tree["dbh_cm"] == round(28.0 * 2.54, 2)
    assert tree["lon"] == -122.6
    assert tree["score"] is not None
    assert tree["public_flag"] is True


def test_stump_row_is_dropped():
    src = _portland_source()
    rec = {"OBJECTID": 1, "Genus_species": "STUMP", "_lon": -122.6, "_lat": 45.5}
    assert build_tree(rec, src, captured_at="2026-07-02") is None


def test_missing_geometry_dropped():
    src = _portland_source()
    rec = {"OBJECTID": 2, "Genus_species": "Quercus rubra"}
    assert build_tree(rec, src, captured_at="2026-07-02") is None


def test_ingest_sample_geojson_end_to_end():
    src = _portland_source()
    rows = ingest_source(src, sample_path=os.path.abspath(SAMPLE))
    # 5 features, 1 is a stump -> 4 trees
    assert len(rows) == 4
    genera = {r["genus"] for r in rows}
    assert "Quercus" in genera
    # Zelkova had null DBH but height present -> estimated DBH used
    zelkova = [r for r in rows if r["genus"] == "Zelkova"][0]
    assert zelkova["score"] is not None
