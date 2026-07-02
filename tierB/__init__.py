"""Tier B — aerial detection + eligibility/hazard reconciliation (spec §4).

Purpose is narrow and explicitly NOT climbability: (a) find trees where no
inventory exists, (b) reconcile public vs private, (c) flag hazard context.
It contributes eligibility gates and score penalties only.
"""

from .detect import (
    DeepForestDetector,
    DetectedCrown,
    Detector,
    GridStubDetector,
    detect_orthophoto,
    georeference,
)
from .parcels import (
    EligibilityResult,
    Hazard,
    OsmContext,
    assess_eligibility,
    context_from_geojson,
)

__all__ = [
    "assess_eligibility",
    "context_from_geojson",
    "detect_orthophoto",
    "georeference",
    "DetectedCrown",
    "Detector",
    "GridStubDetector",
    "DeepForestDetector",
    "EligibilityResult",
    "Hazard",
    "OsmContext",
]
