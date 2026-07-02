"""Pydantic request/response models for the API."""

from __future__ import annotations

from typing import Any, Optional

from pydantic import BaseModel, Field


class BodyParams(BaseModel):
    """User anthropometrics + climbing tunables (all optional, sane defaults)."""

    h: float = Field(1.75, gt=0.5, lt=2.6, description="user height (m)")
    weight: float = Field(70.0, gt=20, lt=250, description="user weight (kg)")
    delta: float = Field(0.60, gt=0.1, lt=1.5, description="comfortable inter-branch step (m)")
    d_min: float = Field(10.0, gt=2, lt=40, description="baseline min load-bearing branch dia (cm)")
    alpha: float = Field(1.22, gt=1.0, lt=1.5, description="ground reach coefficient (UNVERIFIED)")


class TreeOut(BaseModel):
    tree_id: str
    lon: float
    lat: float
    scientific: Optional[str] = None
    genus: Optional[str] = None
    species: Optional[str] = None
    common: Optional[str] = None
    dbh_cm: Optional[float] = None
    height_m: Optional[float] = None
    health: Optional[str] = None
    public_flag: bool = True
    captured_at: Optional[str] = None
    score: Optional[float] = None
    confidence: float = 0.0
    dist_m: Optional[float] = None
    why_scored: Any = None
    provenance: Any = None
    reach_match: Any = None  # per-request form-based guess (or measured ladder)


class QueryResponse(BaseModel):
    count: int
    trees: list[TreeOut]
    body: BodyParams
    disclaimer: str


class ReportIn(BaseModel):
    tree_id: Optional[str] = None
    kind: str = Field(..., pattern="^(correction|takedown|label)$")
    payload: dict = Field(default_factory=dict)
