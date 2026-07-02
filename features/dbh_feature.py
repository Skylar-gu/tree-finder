"""Trunk-size feature from DBH (spec §3.2).

HONESTY (load-bearing, do not soften): DBH is the trunk diameter at breast
height (1.3 m). It is NOT a branch diameter and NOT a first-branch height. A
thick trunk makes a mature, low-scaffold crown *more plausible*, so DBH is used
purely as a size PLAUSIBILITY PRIOR. Every name and doc here keeps that honest;
nothing in this module should ever be read as branch geometry.

The size score is a monotone, saturating function of DBH:
  - below a sapling floor -> heavily penalised (too small to hold a climber),
  - rising through the "interesting" range,
  - saturating near ~60 cm (beyond that, extra girth adds little climbing
    plausibility — you already have a big tree).

When DBH is missing but height is present, we estimate DBH from a genus-generic
height->DBH allometry and mark the result estimated=True (confidence penalty
lives downstream). Allometry constants are coarse literature-style placeholders,
exposed as tunables, NOT physical truths.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Optional

# --- Tunable constants (NOT physical truths) ----------------------------------
SAPLING_FLOOR_CM = 12.0     # below this the tree is too slender to bother with
SATURATION_CM = 60.0        # size score saturates around here
FLOOR_SCORE = 0.05          # score assigned at/below the sapling floor

# Generic height(m) -> DBH(cm) allometry: DBH = a * H^b  (open-grown urban form).
# Placeholder constants in the range of published urban allometries; tune per
# genus in a later tier. See DBH_ALLOMETRY_BY_GENUS for coarse genus overrides.
ALLOMETRY_A = 3.0
ALLOMETRY_B = 1.2

# A few coarse genus overrides (a, b). Absent genus -> generic constants above.
DBH_ALLOMETRY_BY_GENUS: dict[str, tuple[float, float]] = {
    "quercus": (3.4, 1.2),
    "platanus": (3.6, 1.25),
    "populus": (3.8, 1.15),   # tall for their girth
    "eucalyptus": (2.8, 1.2),
    "pinus": (2.6, 1.15),
}


@dataclass
class DbhFeature:
    score: float                 # f_dbh in [0,1]
    dbh_cm_used: Optional[float]  # the DBH value fed to the score (measured or est.)
    estimated: bool              # True if dbh_cm_used came from height allometry
    basis: str                   # "measured" | "height_allometry" | "none"


def _size_score_from_dbh(dbh_cm: float) -> float:
    """Monotone saturating map dbh_cm -> [0,1].

    Uses a smooth logistic-style ramp between the sapling floor and saturation.
    """
    if dbh_cm <= SAPLING_FLOOR_CM:
        return FLOOR_SCORE
    if dbh_cm >= SATURATION_CM:
        return 1.0
    # Normalised position in (floor, saturation), shaped with a smoothstep so the
    # curve eases in above the floor and eases out toward saturation.
    t = (dbh_cm - SAPLING_FLOOR_CM) / (SATURATION_CM - SAPLING_FLOOR_CM)
    smooth = t * t * (3.0 - 2.0 * t)  # smoothstep
    return FLOOR_SCORE + (1.0 - FLOOR_SCORE) * smooth


def estimate_dbh_from_height(height_m: float, genus: Optional[str] = None) -> float:
    """Estimate DBH (cm) from height (m) via coarse allometry. ESTIMATE ONLY."""
    a, b = ALLOMETRY_A, ALLOMETRY_B
    if genus:
        a, b = DBH_ALLOMETRY_BY_GENUS.get(genus.strip().lower(), (a, b))
    return a * math.pow(max(height_m, 0.0), b)


def dbh_size_feature(
    dbh_cm: Optional[float],
    height_m: Optional[float] = None,
    genus: Optional[str] = None,
) -> DbhFeature:
    """Compute the trunk-size plausibility feature.

    Precedence:
      1. measured DBH,
      2. DBH estimated from height (marked estimated),
      3. no size info -> neutral-low score, basis="none".
    """
    if dbh_cm is not None and dbh_cm > 0:
        return DbhFeature(
            score=_size_score_from_dbh(dbh_cm),
            dbh_cm_used=dbh_cm,
            estimated=False,
            basis="measured",
        )

    if height_m is not None and height_m > 0:
        est = estimate_dbh_from_height(height_m, genus)
        return DbhFeature(
            score=_size_score_from_dbh(est),
            dbh_cm_used=round(est, 1),
            estimated=True,
            basis="height_allometry",
        )

    # No size signal at all. Return a modest floor-ish score, not zero, so a tree
    # with a strong species prior is not eliminated purely for missing DBH.
    return DbhFeature(
        score=0.3,
        dbh_cm_used=None,
        estimated=False,
        basis="none",
    )
