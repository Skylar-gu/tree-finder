"""Tiling, cross-seam NMS, and georeferencing (spec §4.2)."""

from tierB.detect import GridStubDetector, detect_orthophoto, georeference, pixel_to_lonlat
from tierB.tiling import Detection, iou, iter_windows, nms, offset_detections


def test_windows_cover_image_and_never_exceed_bounds():
    w, h, tile, overlap = 1000, 800, 400, 100
    windows = list(iter_windows(w, h, tile=tile, overlap=overlap))
    assert windows, "expected at least one window"
    for win in windows:
        assert 0 <= win.x0 <= max(0, w - tile)
        assert 0 <= win.y0 <= max(0, h - tile)
    # Union of window spans reaches the far edges (last tile shifted back).
    assert max(win.x0 + tile for win in windows) >= w
    assert max(win.y0 + tile for win in windows) >= h


def test_offset_translates_to_global_coordinates():
    win = next(iter_windows(1000, 1000, tile=400, overlap=100))
    # Force a non-origin window.
    from tierB.tiling import Window
    win = Window(col=1, row=1, x0=300, y0=300, width=400, height=400)
    local = [Detection(10, 10, 50, 50, score=0.9)]
    g = offset_detections(local, win)[0]
    assert (g.x_min, g.y_min, g.x_max, g.y_max) == (310, 310, 350, 350)


def test_nms_removes_seam_duplicates_keeps_distinct():
    a = Detection(0, 0, 100, 100, score=0.9)
    dup = Detection(5, 5, 105, 105, score=0.8)      # ~0.8 IoU with a -> dropped
    far = Detection(500, 500, 600, 600, score=0.7)  # disjoint -> kept
    assert iou(a, dup) > 0.4
    kept = nms([a, dup, far], iou_threshold=0.4)
    assert len(kept) == 2
    assert a in kept and far in kept and dup not in kept


def test_pixel_to_lonlat_affine():
    # 1 px = 0.6 m ~ NAIP; here a toy transform: origin at (-122.0, 45.0),
    # +x -> +lon, +y -> -lat (north-up rasters have negative e).
    transform = (-122.0, 1e-5, 0.0, 45.0, 0.0, -1e-5)
    assert pixel_to_lonlat(0, 0, transform) == (-122.0, 45.0)
    lon, lat = pixel_to_lonlat(100, 200, transform)
    assert round(lon, 5) == round(-122.0 + 100e-5, 5)
    assert round(lat, 5) == round(45.0 - 200e-5, 5)


def test_detect_orthophoto_end_to_end_with_stub():
    # A 800x800 image, tiled 400/overlap 100, grid stub every 150 px.
    transform = (-122.0, 1e-5, 0.0, 45.0, 0.0, -1e-5)
    crowns = detect_orthophoto(
        width=800, height=800,
        read_tile=lambda win: (win.width, win.height),  # image == (w, h) tuple
        detector=GridStubDetector(spacing=150, box=40),
        transform=transform,
        tile=400, overlap=100,
    )
    assert crowns, "stub should detect crowns"
    # All georeferenced inside the image's world extent.
    for c in crowns:
        assert -122.0 <= c.lon <= -122.0 + 800e-5 + 1e-9
        assert 45.0 - 800e-5 - 1e-9 <= c.lat <= 45.0
    # Overlapping tiles + NMS must not double-count: crowns are unique-ish.
    centres = {(round(c.lon, 6), round(c.lat, 6)) for c in crowns}
    assert len(centres) == len(crowns)


def test_georeference_uses_centroid():
    d = Detection(100, 100, 200, 200, score=0.5)
    transform = (0.0, 1.0, 0.0, 0.0, 0.0, 1.0)  # identity-ish
    crown = georeference(d, transform)
    assert crown.lon == 150 and crown.lat == 150
