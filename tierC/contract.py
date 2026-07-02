"""Tier C output contract (spec §5.3).

Per tree, WHEN street imagery exists, Tier C emits:

    dbh_cm_streetcv     real   + error_band     -- trunk cross-check (reliable-ish)
    lowest_branch_h_m   real   + error_band     -- COARSE, low confidence
    branch_ladder       [{height_m, est_diameter_cm, confidence}]  -- sparse/empty
    tierC_confidence    real

`lowest_branch_h_m` and `branch_ladder` are "the least-supported outputs in the
entire system" (spec §5.3). Everything here therefore carries an explicit error
band, and the pipeline gates the branch outputs behind ``tierC_confidence``
before anything downstream is allowed to treat them as a measured ladder.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional


@dataclass
class Estimate:
    """A value with a symmetric-ish error band. ``band`` is a +/- half-width."""
    value: Optional[float]
    band: Optional[float]
    basis: str = ""          # e.g. "cylinder_fit", "mask_discontinuity"

    def to_dict(self) -> dict:
        return {"value": self.value, "band": self.band, "basis": self.basis}


@dataclass
class BranchRung:
    height_m: float
    est_diameter_cm: float
    confidence: float

    def to_dict(self) -> dict:
        return {
            "height_m": round(self.height_m, 2),
            "est_diameter_cm": round(self.est_diameter_cm, 1),
            "confidence": round(self.confidence, 3),
        }


@dataclass
class TierCOutput:
    """Street-CV geometry for one tree from one frame (method A) or window (B)."""
    dbh_cm_streetcv: Estimate
    lowest_branch_h_m: Estimate
    branch_ladder: list[BranchRung] = field(default_factory=list)
    tierC_confidence: float = 0.0
    image_id: Optional[str] = None
    method: str = "A_monocular"          # "A_monocular" | "B_multiview"
    attribution: Optional[dict] = None   # Mapillary CC-BY-SA credit (see mapillary)
    notes: list[str] = field(default_factory=list)

    def branches_for_reach(self) -> list[tuple[float, float]]:
        """(height_m, diameter_cm) tuples for ``score.reach.reach_match``."""
        return [(r.height_m, r.est_diameter_cm) for r in self.branch_ladder]

    def to_dict(self) -> dict:
        return {
            "dbh_cm_streetcv": self.dbh_cm_streetcv.to_dict(),
            "lowest_branch_h_m": self.lowest_branch_h_m.to_dict(),
            "branch_ladder": [r.to_dict() for r in self.branch_ladder],
            "tierC_confidence": round(self.tierC_confidence, 3),
            "image_id": self.image_id,
            "method": self.method,
            "attribution": self.attribution,
            "notes": self.notes,
        }
