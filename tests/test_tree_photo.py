"""Street View tree-photo logic (offline via injected fetch / no key)."""

import os

from api import photos


def test_no_key_reports_unavailable(monkeypatch):
    monkeypatch.delenv("GOOGLE_MAPS_API_KEY", raising=False)
    monkeypatch.delenv("MAPILLARY_TOKEN", raising=False)
    info = photos.tree_photo_info(37.7749, -122.4194)
    assert info["available"] is False and info["provider"] is None


def test_mapillary_preferred_and_picks_nearest(monkeypatch):
    monkeypatch.setenv("MAPILLARY_TOKEN", "test-token")
    monkeypatch.delenv("GOOGLE_MAPS_API_KEY", raising=False)
    tree = (37.7749, -122.4194)
    far = {"id": "far", "thumb_1024_url": "https://cdn/far.jpg",
           "computed_geometry": {"coordinates": [-122.4199, 37.7753]},
           "captured_at": 1719800000000, "creator": {"username": "alice"}}
    near = {"id": "near", "thumb_1024_url": "https://cdn/near.jpg",
            "computed_geometry": {"coordinates": [-122.41945, 37.77492]},
            "captured_at": 1719800000000, "creator": {"username": "bob"}}
    info = photos.tree_photo_info(*tree, fetch=lambda url, params: {"data": [far, near]})
    assert info["available"] is True and info["provider"] == "mapillary"
    assert info["image"] == "https://cdn/near.jpg"
    assert "pKey=near" in info["url"]
    assert "bob" in info["attribution"] and "CC BY-SA" in info["attribution"]


def test_mapillary_empty_falls_back_to_unavailable(monkeypatch):
    monkeypatch.setenv("MAPILLARY_TOKEN", "test-token")
    monkeypatch.delenv("GOOGLE_MAPS_API_KEY", raising=False)
    info = photos.tree_photo_info(37.7749, -122.4194, fetch=lambda url, params: {"data": []})
    assert info["available"] is False


def test_metadata_ok_computes_heading_toward_tree(monkeypatch):
    monkeypatch.setenv("GOOGLE_MAPS_API_KEY", "test-key")
    # Pano is due SOUTH of the tree -> camera should look ~north (~0deg).
    meta = {"status": "OK", "date": "2023-06", "location": {"lat": 37.7740, "lng": -122.4194}}
    info = photos.tree_photo_info(37.7749, -122.4194, fetch=lambda url, params: meta)
    assert info["available"] is True and info["provider"] == "google"
    assert abs(info["heading"] - 0.0) < 5 or abs(info["heading"] - 360.0) < 5
    assert "Google" in info["attribution"]


def test_metadata_zero_results_unavailable(monkeypatch):
    monkeypatch.setenv("GOOGLE_MAPS_API_KEY", "test-key")
    info = photos.tree_photo_info(0.0, 0.0, fetch=lambda url, params: {"status": "ZERO_RESULTS"})
    assert info["available"] is False


def test_bearing_cardinals():
    # East of origin -> ~90 deg; north -> ~0 deg.
    assert abs(photos._bearing(0, 0, 0, 1) - 90) < 1
    assert abs(photos._bearing(0, 0, 1, 0) - 0) < 1
