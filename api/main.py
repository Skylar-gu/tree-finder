"""FastAPI app (spec §8).

Endpoints:
  GET  /api/health
  GET  /api/trees        radius query + body params -> ranked, reach-matched trees
  GET  /api/trees/aggregate   H3 cell aggregation for zoomed-out viewports
  POST /api/reports      correction / takedown / label queue
  GET  /                 serves the MapLibre frontend

The reach-match runs per request against stored features (no recompute).
"""

from __future__ import annotations

import os

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from .reach_helpers import params_from_body, reach_for_tree
from .schemas import BodyParams, QueryResponse, ReportIn, TreeOut

DISCLAIMER = (
    "Results are a RANKED, CONFIDENCE-TAGGED candidate list — not a safety "
    "certification. Where branch geometry is not measured, reach-match is "
    "a form-based guess. You climb at your own risk under the accepted waiver."
)

FRONTEND_DIR = os.path.join(os.path.dirname(__file__), "..", "frontend")

app = FastAPI(
    title="Climbable-Trees Mapping API",
    version="1.0.0",
    description="Tiers A+B serving (C offline): ranked, confidence-tagged candidate trees. Never certifies safety.",
)
# CORS: lock down in production via ALLOWED_ORIGINS (comma-separated). Defaults
# to "*" for local dev only.
_origins = [o.strip() for o in os.getenv("ALLOWED_ORIGINS", "*").split(",") if o.strip()]
app.add_middleware(
    CORSMiddleware,
    allow_origins=_origins,
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["*"],
)


@app.get("/api/health")
def health():
    return {
        "status": "ok",
        "service": "climbable-trees",
        "certifies_safety": False,
    }


@app.get("/api/cities")
def get_cities():
    """Configured cities (with map centers) for the selector."""
    from db.live_repo import cities

    return {"cities": cities()}


@app.get("/api/trees", response_model=QueryResponse)
def get_trees(
    lon: float = Query(..., ge=-180, le=180),
    lat: float = Query(..., ge=-90, le=90),
    radius_m: float = Query(500.0, gt=0, le=5000),
    h: float = Query(1.75, gt=0.5, lt=2.6),
    weight: float = Query(70.0, gt=20, lt=250),
    delta: float = Query(0.60, gt=0.1, lt=1.5),
    d_min: float = Query(10.0, gt=2, lt=40),
    alpha: float = Query(1.22, gt=1.0, lt=1.5),
    public_only: bool = Query(True),
    min_score: float = Query(0.0, ge=0, le=1),
    limit: int = Query(500, gt=0, le=2000),
):
    from db.repository import query_trees

    rows = query_trees(
        lon=lon,
        lat=lat,
        radius_m=radius_m,
        public_only=public_only,
        min_score=min_score,
        limit=limit,
    )
    params = params_from_body(h, weight, delta, d_min, alpha)

    trees: list[TreeOut] = []
    for r in rows:
        r["reach_match"] = reach_for_tree(r, params)
        r["tree_id"] = str(r.get("tree_id"))
        if r.get("captured_at") is not None:
            r["captured_at"] = str(r["captured_at"])
        trees.append(TreeOut(**{k: r.get(k) for k in TreeOut.model_fields}))

    return QueryResponse(
        count=len(trees),
        trees=trees,
        body=BodyParams(h=h, weight=weight, delta=delta, d_min=d_min, alpha=alpha),
        disclaimer=DISCLAIMER,
    )


@app.get("/api/trees/aggregate")
def aggregate(
    lon: float = Query(..., ge=-180, le=180),
    lat: float = Query(..., ge=-90, le=90),
    radius_m: float = Query(2000.0, gt=0, le=20000),
    resolution: str = Query("h3_r8", pattern="^(h3_r8|h3_r10)$"),
):
    from db.repository import aggregate_h3

    cells = aggregate_h3(lon=lon, lat=lat, radius_m=radius_m, resolution=resolution)
    return {"resolution": resolution, "cells": cells}


@app.post("/api/reports")
def post_report(report: ReportIn):
    from db.repository import insert_report

    if report.kind not in ("correction", "takedown", "label"):
        raise HTTPException(400, "invalid kind")
    rid = insert_report(report.tree_id, report.kind, report.payload)
    return {"report_id": rid, "status": "queued"}


# ------------------------------------------------------------- static frontend
if os.path.isdir(FRONTEND_DIR):
    app.mount("/static", StaticFiles(directory=FRONTEND_DIR), name="static")

    @app.get("/")
    def index():
        return FileResponse(os.path.join(FRONTEND_DIR, "index.html"))
