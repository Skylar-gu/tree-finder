"""Depth + segmentation backends for Tier C method A (spec §5.2).

Two heavy models are needed to turn a street frame into geometry:
  - metric depth (+ intrinsics): **UniDepthV2** (lpiccinelli-eth/UniDepth) is the
    spec's pick because it predicts metric depth AND camera intrinsics jointly,
    so it copes with Mapillary's missing/unreliable EXIF. Metric3Dv2 / Depth Pro
    are alternatives.
  - trunk (and ideally primary-branch) segmentation: a fine-tuned SegFormer or
    YOLO-seg.

Both are imported lazily behind the optional ``requirements-tierc.txt`` extra.
For tests and offline demos we ship deterministic stubs producing a synthetic
``TrunkObservation`` so the whole pipeline runs without torch or imagery.

VERIFY LICENSES AT BUILD TIME (spec §12): UniDepth / Metric3Dv2 / VGGT are
research code with non-permissive or ambiguous terms — matters for a commercial
product.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol


@dataclass
class TrunkObservation:
    """What the segmenter hands the geometry stage for one frame."""
    trunk_width_px: float            # apparent trunk width at breast-height row
    breast_row: float                # image row (v) at ~1.3 m up the trunk
    ground_row: float                # image row (v) of the trunk base
    trunk_center_col: float          # image col (u) of the trunk axis
    branch_rows: list[float] = field(default_factory=list)     # junction rows
    branch_widths_px: list[float] = field(default_factory=list)  # junction widths
    seg_quality: float = 0.5         # [0,1] mask quality proxy


class DepthBackend(Protocol):
    def depth_at(self, u: float, v: float) -> float:  # pragma: no cover - protocol
        """Metric depth (m) at a pixel."""


class Segmenter(Protocol):
    def observe(self, image) -> TrunkObservation:  # pragma: no cover - protocol
        """Segment the trunk + primary branches from a perspective frame."""


# --- Stubs (dependency-free) --------------------------------------------------

@dataclass
class ConstantDepth:
    """A flat depth plane — enough to exercise back-projection math in tests."""
    depth_m: float = 8.0

    def depth_at(self, u: float, v: float) -> float:
        return self.depth_m


@dataclass
class SyntheticTrunkSegmenter:
    """Deterministic trunk + two branch junctions, for tests/offline demos."""
    trunk_width_px: float = 40.0
    branch_heights_px: tuple[float, ...] = (120.0, 240.0)
    branch_widths_px: tuple[float, ...] = (18.0, 12.0)
    ground_row: float = 700.0
    breast_row: float = 620.0
    center_col: float = 400.0
    seg_quality: float = 0.6

    def observe(self, image) -> TrunkObservation:
        return TrunkObservation(
            trunk_width_px=self.trunk_width_px,
            breast_row=self.breast_row,
            ground_row=self.ground_row,
            trunk_center_col=self.center_col,
            branch_rows=list(self.branch_heights_px),
            branch_widths_px=list(self.branch_widths_px),
            seg_quality=self.seg_quality,
        )


# --- Lazy real backends -------------------------------------------------------

class UniDepthV2Backend:
    """Adapter over UniDepthV2 (optional). Predicts metric depth + intrinsics."""

    def __init__(self, model=None, depth_map=None):
        self._model = model
        self._depth_map = depth_map  # a precomputed HxW map, if already inferred

    def _ensure(self):  # pragma: no cover - needs torch
        if self._model is None and self._depth_map is None:
            try:
                from unidepth.models import UniDepthV2  # noqa: WPS433 (lazy)
            except ImportError as exc:
                raise RuntimeError(
                    "UniDepth not installed. `pip install -r requirements-tierc.txt`"
                ) from exc
            self._model = UniDepthV2.from_pretrained("lpiccinelli-eth/unidepth-v2-vitl14")
        return self._model

    def depth_at(self, u: float, v: float) -> float:  # pragma: no cover - needs torch
        if self._depth_map is not None:
            return float(self._depth_map[int(v)][int(u)])
        raise RuntimeError("run inference to populate depth_map before sampling")
