"""Tier C camera + geometry math (spec §5.2)."""

import math

import pytest

from tierC.camera import Camera, PanoramaError
from tierC.geometry import (
    dbh_from_trunk_width,
    fit_cylinder_diameter,
    heights_from_rows,
    metric_width,
)


def _cam(fx=1000.0, w=800, h=1000, is_pano=False):
    return Camera(fx=fx, fy=fx, cx=w / 2, cy=h / 2, width=w, height=h, is_pano=is_pano)


def test_pano_frames_are_refused():
    cam = _cam(is_pano=True)
    with pytest.raises(PanoramaError):
        cam.backproject(400, 500, 8.0)
    with pytest.raises(PanoramaError):
        cam.pixels_per_metre_at(8.0)


def test_from_mapillary_focal_from_camera_parameters():
    cam = Camera.from_mapillary(width=800, height=1000, camera_parameters=[0.5, 0, 0])
    # focal fraction 0.5 of max side (1000) -> 500 px.
    assert cam.fx == pytest.approx(500.0)
    assert cam.cx == 400.0 and cam.cy == 500.0


def test_metric_width_scales_with_depth():
    cam = _cam(fx=1000.0)
    # 40 px wide trunk at 8 m: width_m = 40 / (1000/8) = 0.32 m.
    assert metric_width(40, 8.0, cam) == pytest.approx(0.32, rel=1e-6)
    # Twice as far -> twice as wide in metres for the same pixel span.
    assert metric_width(40, 16.0, cam) == pytest.approx(0.64, rel=1e-6)


def test_dbh_from_trunk_width_has_band():
    cam = _cam(fx=1000.0)
    est = dbh_from_trunk_width(40, 8.0, cam)
    assert est.value == pytest.approx(32.0, rel=1e-3)   # cm
    assert est.band and est.band > 0
    assert est.basis == "trunk_width_monocular"


def test_heights_from_rows_monotone_up():
    cam = _cam(fx=1000.0)
    # ground_row 900, points higher up the image (smaller v) -> greater height.
    hs = heights_from_rows([900, 800, 700], ground_row=900, depth_m=8.0, camera=cam)
    assert hs[0] == pytest.approx(0.0)
    assert hs[1] < hs[2]
    # 100 px up at 8 m, 1000 px focal -> 100/(1000/8) = 0.8 m.
    assert hs[1] == pytest.approx(0.8, rel=1e-6)


def test_cylinder_fit_recovers_known_diameter():
    # Synthesize a circle of radius 0.15 m (30 cm dia) in the X-Z plane.
    r = 0.15
    pts = []
    for k in range(24):
        a = 2 * math.pi * k / 24
        pts.append((r * math.cos(a), 1.3, 8.0 + r * math.sin(a)))
    est = fit_cylinder_diameter(pts)
    assert est.value == pytest.approx(30.0, abs=1.0)   # cm
    assert est.basis == "cylinder_fit"


def test_cylinder_fit_insufficient_points():
    est = fit_cylinder_diameter([(0, 0, 0), (1, 0, 1)])
    assert est.value is None
