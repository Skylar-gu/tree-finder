"""Trunk / branch metric geometry (spec §5.2 method A, step 3).

From a segmented trunk + metric depth we recover:
  - DBH by measuring trunk width at breast height (1.3 m) and converting pixels
    to metres, OR by fitting a circle to a back-projected trunk cross-section.
  - a COARSE branch ladder from detected branch junctions above the trunk,
    each rung carrying an explicit per-rung confidence (spec §5.3).

Honesty (spec §5, §11): trunk DBH-from-photo is an established sub-area, but
per-branch height/diameter from opportunistic street imagery is barely in the
literature. Nothing here claims published accuracies; error bands are wide and
branch confidences are low by construction. Pure math (no numpy needed).
"""

from __future__ import annotations

import math
from typing import Sequence

from .camera import Camera
from .contract import BranchRung, Estimate

# Breast height for DBH (metres). Spec §3.2.
BREAST_HEIGHT_M = 1.3


def metric_width(width_px: float, depth_m: float, camera: Camera) -> float:
    """Convert a fronto-parallel pixel width to metres at ``depth_m``."""
    ppm = camera.pixels_per_metre_at(depth_m)
    return width_px / ppm


def dbh_from_trunk_width(
    width_px: float,
    depth_m: float,
    camera: Camera,
    *,
    depth_rel_err: float = 0.15,
    seg_px_err: float = 3.0,
) -> Estimate:
    """DBH (cm) from trunk pixel width at breast height + its error band.

    The band propagates two dominant errors: relative depth error (metric depth
    models on arbitrary frames are uncertain — spec §11 gap #2) and a few pixels
    of segmentation slop. Deliberately conservative; measure on your own data.
    """
    width_m = metric_width(width_px, depth_m, camera)
    dbh_cm = width_m * 100.0
    # Relative band: depth error scales width linearly; seg error is additive px.
    rel = depth_rel_err + (seg_px_err / max(width_px, 1e-6))
    band_cm = dbh_cm * rel
    return Estimate(value=round(dbh_cm, 1), band=round(band_cm, 1), basis="trunk_width_monocular")


def fit_cylinder_diameter(points: Sequence[tuple[float, float, float]]) -> Estimate:
    """Fit a circle to a back-projected trunk cross-section (Kåsa least squares).

    ``points`` are 3D (X, Y, Z) in the camera frame; we project onto the
    horizontal X-Z plane and fit a circle. Returns diameter in cm. This is the
    higher-fidelity path used when a metric point cloud exists (method B / QSM).
    """
    xs = [p[0] for p in points]
    zs = [p[2] for p in points]
    n = len(xs)
    if n < 3:
        return Estimate(value=None, band=None, basis="cylinder_fit_insufficient")

    # Kåsa algebraic circle fit: minimise |x^2+z^2 + D x + E z + F|.
    sx = sum(xs); sz = sum(zs)
    sxx = sum(x * x for x in xs); szz = sum(z * z for z in zs)
    sxz = sum(x * z for x, z in zip(xs, zs))
    sxxx = sum(x ** 3 for x in xs); szzz = sum(z ** 3 for z in zs)
    sxzz = sum(x * z * z for x, z in zip(xs, zs))
    sxxz = sum(x * x * z for x, z in zip(xs, zs))

    # Solve the 3x3 normal equations for (D, E, F).
    a = [[sxx, sxz, sx], [sxz, szz, sz], [sx, sz, float(n)]]
    b = [-(sxxx + sxzz), -(sxxz + szzz), -(sxx + szz)]
    sol = _solve3(a, b)
    if sol is None:
        return Estimate(value=None, band=None, basis="cylinder_fit_singular")
    d, e, f = sol
    cx, cz = -d / 2.0, -e / 2.0
    r2 = cx * cx + cz * cz - f
    if r2 <= 0:
        return Estimate(value=None, band=None, basis="cylinder_fit_degenerate")
    radius = math.sqrt(r2)
    # Residual spread -> band.
    resid = [abs(math.hypot(x - cx, z - cz) - radius) for x, z in zip(xs, zs)]
    band_cm = (sum(resid) / n) * 100.0 * 2.0
    return Estimate(value=round(2.0 * radius * 100.0, 1), band=round(band_cm, 1), basis="cylinder_fit")


def heights_from_rows(
    rows: Sequence[float], ground_row: float, depth_m: float, camera: Camera
) -> list[float]:
    """Convert image rows (pixels, v-down) to metric heights above ground.

    A point ``ground_row - v`` pixels above the ground line sits that many
    pixels-per-metre up the fronto-parallel plane at ``depth_m``.
    """
    ppm = camera.pixels_per_metre_at(depth_m)
    return [max(0.0, (ground_row - v) / ppm) for v in rows]


def extract_branch_ladder(
    *,
    branch_rows: Sequence[float],
    branch_widths_px: Sequence[float],
    ground_row: float,
    depth_m: float,
    camera: Camera,
    base_confidence: float,
) -> list[BranchRung]:
    """Build a COARSE branch ladder from detected junctions (spec §5.3).

    Each junction is a mask discontinuity / detected primary branch at an image
    row with an apparent width. We convert to (height_m, est_diameter_cm) and
    attach a LOW per-rung confidence that decays with height (higher branches are
    smaller, more occluded, and less reliable). Sparse/empty output is expected.
    """
    heights = heights_from_rows(branch_rows, ground_row, depth_m, camera)
    rungs: list[BranchRung] = []
    for h, w_px in sorted(zip(heights, branch_widths_px)):
        diam_cm = metric_width(w_px, depth_m, camera) * 100.0
        # Confidence decays with height; capped low — these are the least-
        # supported outputs in the whole system.
        conf = max(0.05, base_confidence * math.exp(-h / 8.0))
        rungs.append(
            BranchRung(height_m=h, est_diameter_cm=diam_cm, confidence=round(conf, 3))
        )
    return rungs


def _solve3(a: list[list[float]], b: list[float]):
    """Solve a 3x3 linear system by Cramer's rule; None if near-singular."""
    def det3(m):
        return (
            m[0][0] * (m[1][1] * m[2][2] - m[1][2] * m[2][1])
            - m[0][1] * (m[1][0] * m[2][2] - m[1][2] * m[2][0])
            + m[0][2] * (m[1][0] * m[2][1] - m[1][1] * m[2][0])
        )

    det = det3(a)
    if abs(det) < 1e-12:
        return None
    out = []
    for i in range(3):
        m = [row[:] for row in a]
        for r in range(3):
            m[r][i] = b[r]
        out.append(det3(m) / det)
    return tuple(out)
