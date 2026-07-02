"""Aerial crown detection (spec §4.1).

Tier B's detector finds trees where **no inventory exists** and does nothing
else: it recovers neither trunk nor branch structure, so it contributes **zero
climbability signal** (spec §4). Its output is a set of candidate crown
locations that are then run through eligibility reconciliation (:mod:`parcels`)
and, if kept, ingested as low-confidence, species-unknown trees.

Backends (spec §4.1, §12):
  - ``DeepForest`` (weecology/DeepForest, MIT) — torchvision RetinaNet, bounding
    boxes. The default/fallback; easiest to install. Lazily imported so the core
    package never depends on torch.
  - ``Detectree2`` (better F1 ≈ 0.57 vs 0.52 but needs Detectron2) is left as a
    documented future backend — not wired here.

All detectors satisfy the :class:`Detector` protocol. :func:`detect_orthophoto`
drives tiling + NMS (see :mod:`tiling`) over whatever predictor you inject, so
the pipeline is testable with a stub and never requires imagery or torch.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Optional, Protocol, Sequence

from .tiling import (
    Detection,
    Window,
    iter_windows,
    nms,
    offset_detections,
)

# An affine geotransform mapping pixel (col, row) -> world (lon, lat), in the
# rasterio/GDAL order (c, a, b, f, d, e):  lon = c + a*col + b*row;
# lat = f + d*col + e*row.
GeoTransform = tuple[float, float, float, float, float, float]


class Detector(Protocol):
    """Anything that turns a tile image into tile-local crown boxes."""

    def predict(self, image) -> list[Detection]:  # pragma: no cover - protocol
        ...


@dataclass
class DetectedCrown:
    """A georeferenced aerial detection, ready for eligibility reconciliation."""
    lon: float
    lat: float
    score: float
    px_bbox: tuple[float, float, float, float]


def pixel_to_lonlat(col: float, row: float, transform: GeoTransform) -> tuple[float, float]:
    """Apply a rasterio-order affine geotransform to a pixel coordinate."""
    c, a, b, f, d, e = transform
    return (c + a * col + b * row, f + d * col + e * row)


def georeference(det: Detection, transform: GeoTransform) -> DetectedCrown:
    """Convert a global-pixel detection to a lon/lat crown at its centroid."""
    cx, cy = det.centroid
    lon, lat = pixel_to_lonlat(cx, cy, transform)
    return DetectedCrown(
        lon=lon,
        lat=lat,
        score=det.score,
        px_bbox=(det.x_min, det.y_min, det.x_max, det.y_max),
    )


def detect_orthophoto(
    *,
    width: int,
    height: int,
    read_tile: Callable[[Window], object],
    detector: Detector,
    transform: GeoTransform,
    tile: int = 400,
    overlap: int = 100,
    iou_threshold: float = 0.4,
    min_score: float = 0.2,
) -> list[DetectedCrown]:
    """Tile an orthophoto, detect per tile, stitch with NMS, georeference.

    ``read_tile`` yields the image for a window (e.g. a rasterio windowed read or
    a numpy slice); ``detector`` returns tile-local boxes for it. Neither is
    imported here, keeping this the pure orchestration layer the spec flags as
    the real (CPU/IO-bound) cost.
    """
    global_dets: list[Detection] = []
    for window in iter_windows(width, height, tile=tile, overlap=overlap):
        image = read_tile(window)
        local = [d for d in detector.predict(image) if d.score >= min_score]
        global_dets.extend(offset_detections(local, window))
    merged = nms(global_dets, iou_threshold=iou_threshold)
    return [georeference(d, transform) for d in merged]


class GridStubDetector:
    """Deterministic, dependency-free detector for tests and offline demos.

    Emits one box per ``spacing`` pixels — enough to exercise tiling, seam NMS,
    and georeferencing without torch or imagery.
    """

    def __init__(self, spacing: int = 150, box: int = 40, score: float = 0.9):
        self.spacing = spacing
        self.box = box
        self.score = score

    def predict(self, image) -> list[Detection]:
        w, h = _image_size(image)
        out: list[Detection] = []
        y = self.spacing // 2
        while y < h:
            x = self.spacing // 2
            while x < w:
                out.append(
                    Detection(
                        x_min=x - self.box / 2, y_min=y - self.box / 2,
                        x_max=x + self.box / 2, y_max=y + self.box / 2,
                        score=self.score, label="Tree",
                    )
                )
                x += self.spacing
            y += self.spacing
        return out


class DeepForestDetector:
    """Adapter over weecology/DeepForest (optional extra: ``requirements-tierb``).

    Import is lazy so the core package never pulls in torch. Verify the current
    install + license from the repo at build time (spec §12 note).
    """

    def __init__(self, model=None):
        self._model = model

    def _ensure_model(self):
        if self._model is None:
            try:
                from deepforest import main as _df_main  # noqa: WPS433 (lazy)
            except ImportError as exc:  # pragma: no cover - env-dependent
                raise RuntimeError(
                    "DeepForest not installed. `pip install -r requirements-tierb.txt`"
                ) from exc
            model = _df_main.deepforest()
            model.use_release()
            self._model = model
        return self._model

    def predict(self, image) -> list[Detection]:  # pragma: no cover - needs torch
        model = self._ensure_model()
        df = model.predict_image(image=image, return_plot=False)
        if df is None:
            return []
        return [
            Detection(
                x_min=float(r.xmin), y_min=float(r.ymin),
                x_max=float(r.xmax), y_max=float(r.ymax),
                score=float(getattr(r, "score", 1.0)), label=str(getattr(r, "label", "Tree")),
            )
            for r in df.itertuples()
        ]


def _image_size(image) -> tuple[int, int]:
    """Best-effort (width, height) for numpy arrays, PILs, or (w, h) tuples."""
    if hasattr(image, "shape"):        # numpy: (H, W, C)
        h, w = image.shape[0], image.shape[1]
        return int(w), int(h)
    if hasattr(image, "size"):         # PIL: (W, H)
        w, h = image.size
        return int(w), int(h)
    if isinstance(image, Sequence) and len(image) == 2:
        return int(image[0]), int(image[1])
    raise TypeError(f"cannot determine image size for {type(image)!r}")
