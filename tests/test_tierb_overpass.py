"""Overpass -> OsmContext parsing + reconciliation wiring (offline)."""

from score.climbability import score_tree
from tierB.overpass import elements_to_context, fetch_osm_context
from tierB.parcels import assess_eligibility


def test_elements_to_context_classifies_ways():
    elements = [
        {"type": "way", "tags": {"landuse": "residential"},
         "geometry": [{"lon": -122.0, "lat": 45.0}, {"lon": -121.99, "lat": 45.0},
                      {"lon": -121.99, "lat": 45.01}, {"lon": -122.0, "lat": 45.01}]},
        {"type": "way", "tags": {"leisure": "park"},
         "geometry": [{"lon": -122.1, "lat": 45.0}, {"lon": -122.09, "lat": 45.0},
                      {"lon": -122.09, "lat": 45.01}]},
        {"type": "way", "tags": {"power": "line"},
         "geometry": [{"lon": -122.0, "lat": 45.0}, {"lon": -122.0, "lat": 45.02}]},
        {"type": "node", "tags": {"power": "tower"}},          # ignored
        {"type": "way", "tags": {"power": "line"}, "geometry": [{"lon": -1, "lat": 1}]},  # <2 pts
    ]
    ctx = elements_to_context(elements)
    tags = {f.tag for f in ctx.polygons}
    assert ("landuse", "residential") in tags
    assert ("leisure", "park") in tags
    assert len(ctx.lines) == 1 and ctx.lines[0].kind == "power_line"


def test_fetch_osm_context_uses_injected_fetch_and_reconciles():
    payload = {"elements": [
        {"type": "way", "tags": {"landuse": "residential"},
         "geometry": [{"lon": -122.001, "lat": 44.999}, {"lon": -121.999, "lat": 44.999},
                      {"lon": -121.999, "lat": 45.001}, {"lon": -122.001, "lat": 45.001}]},
    ]}
    ctx = fetch_osm_context(-122.0, 45.0, 500, fetch=lambda url, data: payload)
    r = assess_eligibility(-122.0, 45.0, ctx, incoming_public_flag=True)
    assert r.excluded is True                    # inside the residential parcel
    res = score_tree(genus="Quercus", dbh_cm=50, tierb=r)
    assert res.eligible is False


def test_fetch_osm_context_empty_on_failure():
    def boom(url, data):
        raise RuntimeError("overpass down")
    ctx = fetch_osm_context(-122.0, 45.0, 500, fetch=boom)
    assert ctx.polygons == [] and ctx.lines == []
