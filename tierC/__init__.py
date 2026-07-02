"""Tier C — street-level geometry (spec §5).

The hard, valuable part: recover trunk DBH (reliable-ish) and a COARSE, low-
confidence branch ladder from opportunistic Mapillary street imagery. Trunk
DBH-from-photo is established; per-branch geometry from street imagery is barely
in the literature, so branch outputs are confidence-gated by construction.
"""

from .backends import (
    ConstantDepth,
    DepthBackend,
    Segmenter,
    SyntheticTrunkSegmenter,
    TrunkObservation,
    UniDepthV2Backend,
)
from .camera import Camera, PanoramaError
from .contract import BranchRung, Estimate, TierCOutput
from .mapillary import MapillaryClient, MapillaryImage, attribution_for
from .pipeline import (
    BRANCH_GATE,
    gated_branches,
    run_monocular,
    streetcv_feature,
)

__all__ = [
    "Camera",
    "PanoramaError",
    "TierCOutput",
    "Estimate",
    "BranchRung",
    "TrunkObservation",
    "DepthBackend",
    "Segmenter",
    "ConstantDepth",
    "SyntheticTrunkSegmenter",
    "UniDepthV2Backend",
    "MapillaryClient",
    "MapillaryImage",
    "attribution_for",
    "run_monocular",
    "streetcv_feature",
    "gated_branches",
    "BRANCH_GATE",
]
