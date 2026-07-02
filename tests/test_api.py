import pytest

pytest.importorskip("fastapi")
from fastapi.testclient import TestClient  # noqa: E402

import db.repository as repo  # noqa: E402
from api.main import app  # noqa: E402
from score.climbability import score_tree  # noqa: E402

client = TestClient(app)


def _fake_row():
    scored = score_tree(genus="Quercus", species="rubra", dbh_cm=45, captured_at_fresh=True)
    return {
        "tree_id": "00000000-0000-0000-0000-000000000001",
        "lon": -122.6,
        "lat": 45.5,
        "scientific": "Quercus rubra",
        "genus": "Quercus",
        "species": "rubra",
        "common": "Red Oak",
        "dbh_cm": 45.0,
        "height_m": None,
        "health": "Good",
        "public_flag": True,
        "captured_at": "2026-07-02",
        "score": scored.score,
        "confidence": scored.confidence,
        "why_scored": scored.why_scored,
        "provenance": scored.provenance,
        "dist_m": 12.3,
    }


def test_health():
    r = client.get("/api/health")
    assert r.status_code == 200
    assert r.json()["certifies_safety"] is False


def test_trees_runs_reach_match_per_request(monkeypatch):
    monkeypatch.setattr(repo, "query_trees", lambda **kw: [_fake_row()])
    r = client.get("/api/trees", params={"lon": -122.6, "lat": 45.5, "weight": 90})
    assert r.status_code == 200
    body = r.json()
    assert body["count"] == 1
    tree = body["trees"][0]
    # v1 reach-match must be a form-based guess, never a measured ladder
    rm = tree["reach_match"]
    assert rm["is_measured_ladder"] is False
    assert rm["mode"] == "form_based_guess"
    assert rm["ladder"] == []
    # heavier user -> larger effective d_min than baseline 10cm
    assert rm["effective_d_min_cm"] > 10.0
    assert "not a safety certification" in body["disclaimer"].lower()


def test_report_endpoint(monkeypatch):
    monkeypatch.setattr(repo, "insert_report", lambda t, k, p: "rid-123")
    r = client.post("/api/reports", json={"tree_id": None, "kind": "correction", "payload": {"note": "wrong species"}})
    assert r.status_code == 200
    assert r.json()["report_id"] == "rid-123"
