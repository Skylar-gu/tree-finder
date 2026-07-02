"""Tier C Mapillary client — offline via injected fetch (spec §5.1)."""

from tierC.mapillary import (
    MapillaryClient,
    MapillaryImage,
    attribution_for,
    lonlat_to_tile,
)


def test_tile_coords_in_range():
    x, y = lonlat_to_tile(-122.6765, 45.5231, z=14)
    assert 0 <= x < 2 ** 14 and 0 <= y < 2 ** 14


def test_attribution_block_demands_credit():
    img = MapillaryImage(
        image_id="123", lon=-122.0, lat=45.0, is_pano=False,
        camera_parameters=[0.5], compass_angle=90, captured_at=0, quality_score=0.8,
    )
    a = attribution_for(img)
    assert a["license"] == "CC-BY-SA 4.0"
    assert a["logo_required"] is True
    assert "123" in a["image_url"]


def _tile_fetch(features):
    def fetch(url, params=None, headers=None):
        return {"features": features}
    return fetch


def test_nearest_image_filters_radius_and_panos():
    features = [
        # ~11 m away, perspective -> candidate
        {"geometry": {"coordinates": [-122.00010, 45.0]},
         "properties": {"id": "near", "is_pano": False, "camera_parameters": [0.5]}},
        # ~1 m away but pano -> excluded
        {"geometry": {"coordinates": [-122.00001, 45.0]},
         "properties": {"id": "pano", "is_pano": True}},
        # far away -> excluded by radius
        {"geometry": {"coordinates": [-122.01, 45.0]},
         "properties": {"id": "far", "is_pano": False}},
    ]
    client = MapillaryClient(token="ML|test", fetch=_tile_fetch(features))
    img = client.nearest_image(-122.0, 45.0, radius_m=30.0, exclude_pano=True)
    assert img is not None and img.image_id == "near"


def test_nearest_image_none_when_all_panos():
    features = [
        {"geometry": {"coordinates": [-122.00001, 45.0]},
         "properties": {"id": "p1", "is_pano": True}},
    ]
    client = MapillaryClient(token="ML|test", fetch=_tile_fetch(features))
    assert client.nearest_image(-122.0, 45.0) is None


def test_image_meta_uses_graph_fetch():
    def fetch(url, params=None, headers=None):
        assert "graph.mapillary.com" in url
        assert headers["Authorization"].startswith("OAuth ")
        return {"id": "42", "geometry": {"coordinates": [-122.0, 45.0]},
                "is_pano": False, "camera_parameters": [0.5], "quality_score": 0.7}
    client = MapillaryClient(token="MLY|abc", fetch=fetch)
    img = client.image_meta("42")
    assert img.image_id == "42" and img.quality_score == 0.7
