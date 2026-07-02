"""Eligibility gate + hazard penalty reconciliation (spec §4.2)."""

import json
import os

from tierB.geometry import point_in_polygon, point_to_line_m
from tierB.parcels import (
    LineFeature,
    OsmContext,
    PolygonFeature,
    assess_eligibility,
    context_from_geojson,
)

DATA = os.path.join(os.path.dirname(__file__), "..", "data")


def _square(cx, cy, half):
    return [[
        [cx - half, cy - half], [cx + half, cy - half],
        [cx + half, cy + half], [cx - half, cy + half], [cx - half, cy - half],
    ]]


def test_point_in_polygon_and_holes():
    outer = [(0, 0), (10, 0), (10, 10), (0, 10)]
    hole = [(4, 4), (6, 4), (6, 6), (4, 6)]
    assert point_in_polygon((1, 1), [outer])
    assert not point_in_polygon((5, 5), [outer, hole])   # in the hole
    assert point_in_polygon((5, 1), [outer, hole])       # outside the hole


def test_point_to_line_distance_metres():
    # Vertical line at lon 0 from lat 0..0.001; point ~ due east.
    line = [(0.0, 0.0), (0.0, 0.001)]
    d = point_to_line_m((0.0001, 0.0005), line)  # ~0.0001 deg lon east
    assert 8.0 < d < 14.0  # ~11 m at the equator


def test_private_parcel_excludes():
    ctx = OsmContext(polygons=[
        PolygonFeature(tag=("landuse", "residential"), polygon=_square(-122.0, 45.0, 0.001)),
    ])
    r = assess_eligibility(-122.0, 45.0, ctx, incoming_public_flag=True)
    assert r.public_flag is False
    assert r.excluded is True
    assert "B:parcels" in r.tiers


def test_public_park_confirms_eligible():
    ctx = OsmContext(polygons=[
        PolygonFeature(tag=("leisure", "park"), polygon=_square(-122.0, 45.0, 0.001)),
    ])
    r = assess_eligibility(-122.0, 45.0, ctx, incoming_public_flag=True)
    assert r.public_flag is True and r.excluded is False


def test_no_containment_keeps_incoming_flag():
    ctx = OsmContext()  # empty
    assert assess_eligibility(-122.0, 45.0, ctx, incoming_public_flag=True).public_flag is True
    # aerial-detected with no prior -> defaults public (biased public stock)
    r = assess_eligibility(-122.0, 45.0, ctx, incoming_public_flag=None, detected=True)
    assert r.public_flag is True and "B:aerial" in r.tiers


def test_power_line_proximity_penalises_not_excludes():
    ctx = OsmContext(lines=[
        LineFeature(kind="power_line", line=[(-122.0, 45.0), (-122.0, 45.001)]),
    ])
    # ~4 m east of the line -> tightest power band (x0.25).
    r = assess_eligibility(-122.0 + 0.00005, 45.0005, ctx)
    assert r.excluded is False           # hazards never exclude
    assert r.penalty < 0.5
    assert any(h.kind == "power_line" for h in r.hazards)


def test_far_hazard_has_no_effect():
    ctx = OsmContext(lines=[
        LineFeature(kind="power_line", line=[(-122.0, 45.0), (-122.0, 45.001)]),
    ])
    r = assess_eligibility(-122.0 + 0.01, 45.0005, ctx)  # ~780 m away
    assert r.penalty == 1.0 and not r.hazards


def test_context_from_geojson_classifies_features():
    with open(os.path.join(DATA, "sample_portland_osm.geojson"), encoding="utf-8") as fh:
        ctx = context_from_geojson(json.load(fh))
    tags = {f.tag for f in ctx.polygons}
    assert ("leisure", "park") in tags
    assert ("landuse", "residential") in tags
    assert any(l.kind == "power_line" for l in ctx.lines)
