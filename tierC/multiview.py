"""Tier C method B — feed-forward multiview (spec §5.2 B). INTERFACE STUB.

Mapillary frames come in *sequences* — consecutive views of the same trees.
Feeding a short window to a feed-forward geometry model (**VGGT**, or the newer
**MapAnything** lineage) yields a metric point cloud without per-scene SfM
optimisation; trunk/branch geometry is then fit on the cloud (reuse
``geometry.fit_cylinder_diameter``). This resolves scale/occlusion far better
than single-frame monocular and is the right long-term Tier C. It is also "the
one place GPU memory matters" (memory grows with frame count) — a 24–48 GB card.

Close published template: **UrbanVGGT** (arXiv 2603.22531, 2026) does scalable
sidewalk-width estimation from street view via exactly this recipe.

This module intentionally only defines the seam. Wiring VGGT/MapAnything is
deferred; verify their licenses before commercial use (spec §12).
"""

from __future__ import annotations

from typing import Protocol, Sequence


class MultiviewReconstructor(Protocol):
    def point_cloud(self, frames: Sequence) -> list[tuple[float, float, float]]:
        """Return a metric point cloud (camera or world frame) for the window."""
        ...


def reconstruct_and_fit(*args, **kwargs):  # pragma: no cover - not wired in v3
    raise NotImplementedError(
        "Tier C method B (VGGT/MapAnything multiview) is a documented seam, not "
        "yet wired. Use run_monocular (method A) for now; see multiview.py."
    )
