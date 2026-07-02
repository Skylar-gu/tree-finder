"""Tier C method A — single-frame metric monocular pipeline (spec §5.2 A).

Given a tree location and a nearby perspective Mapillary frame:
  1. segment the trunk (+ visible primary branches),
  2. sample metric depth,
  3. back-project / measure to get DBH at 1.3 m and a COARSE branch ladder.

Everything is confidence-gated (spec §5.3): ``lowest_branch_h_m`` and the branch
ladder are the least-supported outputs in the system, so below ``BRANCH_GATE``
they are withheld from the reach-match and scoring even though the DBH
cross-check may still be usable.

Method B (feed-forward multiview over a sequence — VGGT / MapAnything) is the
higher-fidelity path (spec §5.2 B); its interface is stubbed in ``multiview.py``.
"""

from __future__ import annotations

from typing import Optional

from .backends import DepthBackend, Segmenter, TrunkObservation
from .camera import Camera, PanoramaError
from .contract import Estimate, TierCOutput
from .geometry import (
    BREAST_HEIGHT_M,
    dbh_from_trunk_width,
    extract_branch_ladder,
    heights_from_rows,
)
from .mapillary import MapillaryImage, attribution_for

# Below this Tier C confidence, branch-ladder outputs are NOT trusted downstream.
BRANCH_GATE = 0.35


def run_monocular(
    *,
    image,
    camera: Camera,
    depth: DepthBackend,
    segmenter: Segmenter,
    mly_image: Optional[MapillaryImage] = None,
) -> TierCOutput:
    """Run method A on one frame. Raises nothing for panos — returns a low-conf,
    empty result so the caller can skip gracefully."""
    image_id = mly_image.image_id if mly_image else None
    attribution = attribution_for(mly_image) if mly_image else None

    if camera.is_pano:
        return _empty(
            image_id, attribution,
            note="frame is equirectangular (is_pano) — pinhole geometry invalid, skipped",
        )

    obs: TrunkObservation = segmenter.observe(image)
    try:
        z = depth.depth_at(obs.trunk_center_col, obs.breast_row)
    except Exception as exc:  # depth unavailable for this pixel
        return _empty(image_id, attribution, note=f"depth unavailable: {exc}")
    if z <= 0:
        return _empty(image_id, attribution, note="non-positive depth")

    # --- DBH cross-check (the reliable-ish output) ----------------------------
    dbh = dbh_from_trunk_width(obs.trunk_width_px, z, camera)

    # --- Lowest branch height + ladder (coarse, low confidence) ---------------
    if obs.branch_rows:
        lowest_h = min(
            heights_from_rows(obs.branch_rows, obs.ground_row, z, camera)
        )
        lowest = Estimate(
            value=round(lowest_h, 2),
            band=round(max(0.3, 0.2 * lowest_h), 2),  # >= 30 cm band, grows with height
            basis="mask_discontinuity",
        )
    else:
        lowest = Estimate(value=None, band=None, basis="no_branch_junction_detected")

    # --- Confidence: seg quality x depth trust x frame quality ----------------
    tierc_conf = _confidence(obs, mly_image)

    ladder = []
    notes = [
        "Tier C branch geometry is COARSE and low-confidence by construction "
        "(spec §5.3). DBH cross-check is the reliable win.",
    ]
    if tierc_conf >= BRANCH_GATE and obs.branch_rows:
        ladder = extract_branch_ladder(
            branch_rows=obs.branch_rows,
            branch_widths_px=obs.branch_widths_px,
            ground_row=obs.ground_row,
            depth_m=z,
            camera=camera,
            base_confidence=tierc_conf,
        )
    elif obs.branch_rows:
        notes.append(
            f"branch ladder WITHHELD: tierC_confidence {tierc_conf:.2f} < gate {BRANCH_GATE}"
        )

    return TierCOutput(
        dbh_cm_streetcv=dbh,
        lowest_branch_h_m=lowest,
        branch_ladder=ladder,
        tierC_confidence=tierc_conf,
        image_id=image_id,
        method="A_monocular",
        attribution=attribution,
        notes=notes,
    )


def _empty(image_id, attribution, *, note: str) -> TierCOutput:
    """A zero-confidence result for frames we cannot use (pano, no depth, ...)."""
    return TierCOutput(
        dbh_cm_streetcv=Estimate(value=None, band=None, basis="unusable_frame"),
        lowest_branch_h_m=Estimate(value=None, band=None, basis="unusable_frame"),
        branch_ladder=[],
        tierC_confidence=0.0,
        image_id=image_id,
        method="A_monocular",
        attribution=attribution,
        notes=[note],
    )


def _confidence(obs: TrunkObservation, mly: Optional[MapillaryImage]) -> float:
    """Blend segmentation quality with frame quality into [0, ~0.7].

    Capped below 1.0: even a clean monocular frame gives coarse branch geometry.
    """
    c = 0.5 * obs.seg_quality
    q = getattr(mly, "quality_score", None) if mly else None
    if q is not None:
        c += 0.3 * max(0.0, min(1.0, float(q)))
    else:
        c += 0.10
    # A trunk with a plausible breast/ground separation earns a little more.
    if obs.ground_row > obs.breast_row:
        c += 0.10
    return round(min(c, 0.70), 3)


def gated_branches(output: TierCOutput) -> list[tuple[float, float]]:
    """Branches to feed ``reach_match`` — empty unless the gate passed."""
    if output.tierC_confidence < BRANCH_GATE:
        return []
    return output.branches_for_reach()


def streetcv_feature(
    output: TierCOutput, *, h_ref: float = 5.0
) -> Optional[float]:
    """Tier C climbability contribution ``f_streetcv`` in [0,1], or None.

    Returns None below the confidence gate so ``score_tree`` keeps ``w_c``
    dormant (as in v1) rather than trusting weak imagery. When trusted, it
    rewards a LOW measured lowest branch (a reachable scaffold actually seen),
    which is exactly the signal Tier A can only guess at.
    """
    if output.tierC_confidence < BRANCH_GATE:
        return None
    lb = output.lowest_branch_h_m.value
    if lb is None:
        return None
    # Lower first branch -> higher climbability feature; clamp to [0,1].
    return round(max(0.0, min(1.0, 1.0 - lb / h_ref)), 4)
