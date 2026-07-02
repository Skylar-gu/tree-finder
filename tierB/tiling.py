"""Orthophoto tiling + cross-seam NMS (spec §4.2).

The spec is explicit that for Tier B "tiling large orthophotos (windowing +
stitching + NMS across tile seams) is the real engineering cost here and is
CPU/IO-bound, not GPU-bound." This module is that cost, isolated and pure: it
knows nothing about any particular detector or image library, so it is fully
unit-testable without torch or rasterio.

A detection box is in GLOBAL pixel coordinates of the source orthophoto:
``(x_min, y_min, x_max, y_max, score, label)``.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterator


@dataclass(frozen=True)
class Window:
    """A tile window in global pixel space, with its overlap-aware read box."""
    col: int
    row: int
    x0: int
    y0: int
    width: int
    height: int


@dataclass
class Detection:
    """A crown detection in GLOBAL orthophoto pixel coordinates."""
    x_min: float
    y_min: float
    x_max: float
    y_max: float
    score: float = 1.0
    label: str = "Tree"

    @property
    def area(self) -> float:
        return max(0.0, self.x_max - self.x_min) * max(0.0, self.y_max - self.y_min)

    @property
    def centroid(self) -> tuple[float, float]:
        return ((self.x_min + self.x_max) / 2.0, (self.y_min + self.y_max) / 2.0)


def iter_windows(
    width: int, height: int, tile: int = 400, overlap: int = 100
) -> Iterator[Window]:
    """Yield overlapping tile windows covering a ``width`` x ``height`` image.

    ``overlap`` (in pixels) makes crowns straddling a seam visible in at least
    one tile whole; the duplicate detections it creates are removed later by
    :func:`nms`. The last row/column is shifted back so it never runs past the
    image edge (rather than emitting a ragged partial tile).
    """
    if tile <= 0 or overlap < 0 or overlap >= tile:
        raise ValueError("require tile > 0 and 0 <= overlap < tile")
    step = tile - overlap
    xs = list(range(0, max(1, width - overlap), step))
    ys = list(range(0, max(1, height - overlap), step))
    for row, y in enumerate(ys):
        y0 = min(y, max(0, height - tile))
        for col, x in enumerate(xs):
            x0 = min(x, max(0, width - tile))
            yield Window(
                col=col, row=row, x0=x0, y0=y0,
                width=min(tile, width), height=min(tile, height),
            )


def offset_detections(dets: list[Detection], window: Window) -> list[Detection]:
    """Translate tile-local detections into global orthophoto coordinates."""
    return [
        Detection(
            x_min=d.x_min + window.x0,
            y_min=d.y_min + window.y0,
            x_max=d.x_max + window.x0,
            y_max=d.y_max + window.y0,
            score=d.score,
            label=d.label,
        )
        for d in dets
    ]


def iou(a: Detection, b: Detection) -> float:
    """Intersection-over-union of two boxes."""
    ix0 = max(a.x_min, b.x_min)
    iy0 = max(a.y_min, b.y_min)
    ix1 = min(a.x_max, b.x_max)
    iy1 = min(a.y_max, b.y_max)
    iw = max(0.0, ix1 - ix0)
    ih = max(0.0, iy1 - iy0)
    inter = iw * ih
    if inter <= 0.0:
        return 0.0
    union = a.area + b.area - inter
    return inter / union if union > 0 else 0.0


def nms(dets: list[Detection], iou_threshold: float = 0.4) -> list[Detection]:
    """Greedy non-max suppression to remove cross-seam duplicate crowns.

    Highest-scoring boxes win; any lower box overlapping a kept box by more than
    ``iou_threshold`` is suppressed. This is what stitches per-tile results back
    into one clean detection set.
    """
    kept: list[Detection] = []
    for d in sorted(dets, key=lambda x: x.score, reverse=True):
        if all(iou(d, k) <= iou_threshold for k in kept):
            kept.append(d)
    return kept
