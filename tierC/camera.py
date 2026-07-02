"""Pinhole camera model + back-projection (spec §5.2 method A, step 3).

Given a pixel and a metric depth we back-project to a 3D point in the camera
frame:  X = (u - cx)/fx * Z,  Y = (v - cy)/fy * Z,  Z = depth.

Two hard constraints from the spec are enforced here:
  - **Panorama gotcha (§5.1):** a large share of Mapillary frames are 360°
    equirectangular (``is_pano=true``). Pinhole triangulation is INVALID on them.
    :func:`require_pinhole` refuses them so Tier C v1 stays on perspective frames.
  - Intrinsics may be missing/unreliable; ``camera_parameters`` (or a metric
    depth model that predicts intrinsics, e.g. UniDepthV2) provides them.

Pure math, no numpy required (works on plain lists), so it is unit-testable.
"""

from __future__ import annotations

from dataclasses import dataclass


class PanoramaError(ValueError):
    """Raised when a pinhole operation is attempted on an equirectangular frame."""


@dataclass
class Camera:
    """Pinhole intrinsics in pixels."""
    fx: float
    fy: float
    cx: float
    cy: float
    width: int
    height: int
    is_pano: bool = False

    @classmethod
    def from_mapillary(
        cls,
        *,
        width: int,
        height: int,
        camera_parameters: list[float] | None = None,
        is_pano: bool = False,
    ) -> "Camera":
        """Build intrinsics from Mapillary ``camera_parameters`` = [f, k1, k2].

        Mapillary reports focal length as a fraction of the larger image side;
        principal point is assumed central (the Graph API does not expose it).
        Distortion (k1, k2) is ignored here — a documented v1 simplification.
        """
        if camera_parameters:
            f_frac = float(camera_parameters[0])
            f_px = f_frac * max(width, height)
        else:
            # No intrinsics at all: fall back to a ~60° HFOV guess. Callers should
            # prefer a depth model that predicts intrinsics (UniDepthV2).
            f_px = 0.5 * width / _tan_half_hfov(60.0)
        return cls(
            fx=f_px, fy=f_px, cx=width / 2.0, cy=height / 2.0,
            width=width, height=height, is_pano=is_pano,
        )

    def require_pinhole(self) -> None:
        if self.is_pano:
            raise PanoramaError(
                "equirectangular (is_pano) frame — pinhole triangulation invalid; "
                "reproject a perspective crop first or skip (spec §5.1)"
            )

    def backproject(self, u: float, v: float, depth: float) -> tuple[float, float, float]:
        """Pixel (u, v) + metric depth Z -> 3D point (X, Y, Z) in camera frame."""
        self.require_pinhole()
        x = (u - self.cx) / self.fx * depth
        y = (v - self.cy) / self.fy * depth
        return (x, y, depth)

    def pixels_per_metre_at(self, depth: float) -> float:
        """Image scale (px per metre) of a fronto-parallel surface at ``depth``.

        Used to convert a trunk's pixel width into a metric width when a full
        back-projected cloud is not needed (fast DBH cross-check).
        """
        self.require_pinhole()
        if depth <= 0:
            raise ValueError("depth must be positive")
        return self.fx / depth


def _tan_half_hfov(hfov_deg: float) -> float:
    import math

    return math.tan(math.radians(hfov_deg) / 2.0)
