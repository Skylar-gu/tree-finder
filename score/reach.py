"""Reach-match filter (spec §7.2).

Given a user's body (height ``h``, ``weight``, comfortable inter-branch step
``delta``, minimum load-bearing branch diameter ``d_min``) and a tree's ordered
branch heights + diameters, decide how high the user could plausibly climb via a
reachable ladder of sufficiently-thick branches.

    Mount:  min(load-bearing branches) <= R0 + m
    Ladder: b_{i+1} - b_i <= delta + reach_from_standing_on(b_i)
    H     : highest branch reached before the ladder breaks.

CRITICAL v1 BEHAVIOUR (spec §7.2 DEGRADATION):
    No tree inventory contains per-branch heights/diameters (spec §2 — there is
    NO lowest-branch field in ANY source). So in v1 the real ladder NEVER runs.
    Instead ``reach_match`` falls back to a species-form + DBH plausibility score,
    returned with ``mode="form_based_guess"`` and ``is_measured_ladder=False``.
    We NEVER synthesise fake branch heights to fabricate a ladder.

ANTHROPOMETRIC & LOAD CONSTANTS ARE TUNABLES, NOT TRUTHS (spec §11 gap #4).
The load side (section modulus ~ pi*d^3/32) is used ONLY to scale ``d_min`` as a
plausibility filter. We NEVER emit a load rating (invariant #1).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional


# --- Tunable anthropometric / load constants (NOT physical truths) ------------
@dataclass
class ReachParams:
    """User body + climbing tunables. Every default is a placeholder.

    alpha           : ground standing reach coefficient, R0 = alpha * h.
                      Literature puts fingertip standing reach near 1.2-1.25 x
                      stature; UNVERIFIED for this use — expose, don't hardcode.
    mount_margin_m  : optional jump/pull margin added at the mount (m).
    delta           : comfortable inter-branch vertical step (m), default ~0.6.
    d_min_cm        : baseline min load-bearing branch diameter (cm), default 10.
    ref_weight_kg   : reference body weight the baseline d_min was chosen for.
    standing_reach_frac : reach ABOVE the feet while standing on a branch, as a
                      fraction of stature (grab-and-pull the next limb).
    """

    h_m: float = 1.75
    weight_kg: float = 70.0
    alpha: float = 1.22
    mount_margin_m: float = 0.30
    delta: float = 0.60
    d_min_cm: float = 10.0
    ref_weight_kg: float = 70.0
    standing_reach_frac: float = 0.90

    @property
    def ground_reach_m(self) -> float:
        """R0 = alpha * h."""
        return self.alpha * self.h_m

    @property
    def effective_d_min_cm(self) -> float:
        """Scale baseline d_min by body weight via section-modulus (~d^3) logic.

        Bending capacity of a round section scales with d^3, so to carry a load
        proportional to body weight the minimum sound diameter scales with
        weight^(1/3). This ONLY sets the filter threshold; it is NOT a load
        rating and must never be presented as one.
        """
        scale = (self.weight_kg / self.ref_weight_kg) ** (1.0 / 3.0)
        return self.d_min_cm * scale

    def allowed_gap_m(self) -> float:
        """Max vertical gap to the next branch = delta + reach while standing."""
        return self.delta + self.standing_reach_frac * self.h_m


@dataclass
class ReachResult:
    mode: str                       # "measured_ladder" | "form_based_guess"
    is_measured_ladder: bool
    reachable: bool                 # could the user mount + climb at all?
    reachable_height_m: Optional[float]  # H (measured mode only)
    ladder: list[dict] = field(default_factory=list)  # retained branches (measured only)
    plausibility: Optional[float] = None  # [0,1] form-based guess (degraded mode)
    confidence: float = 0.0
    effective_d_min_cm: float = 0.0
    notes: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "mode": self.mode,
            "is_measured_ladder": self.is_measured_ladder,
            "reachable": self.reachable,
            "reachable_height_m": self.reachable_height_m,
            "ladder": self.ladder,
            "plausibility": self.plausibility,
            "confidence": self.confidence,
            "effective_d_min_cm": round(self.effective_d_min_cm, 2),
            "notes": self.notes,
        }


def _measured_ladder(
    branches: list[tuple[float, float]],
    p: ReachParams,
    ladder_confidence: float = 0.9,
) -> ReachResult:
    """Run the real mount+ladder logic. Only reachable when branch data exists.

    branches: list of (height_m, diameter_cm), any order.
    ladder_confidence: trust in the branch measurements themselves. Premium
        phone-LiDAR/QSM is high (~0.9, the default); opportunistic Tier C street
        imagery is COARSE and low-confidence by construction (spec §5.3), so the
        Tier C pipeline passes its ``tierC_confidence`` here instead.
    """
    d_min = p.effective_d_min_cm
    # Keep only load-bearing branches, sorted by height.
    load_bearing = sorted(
        [(h, d) for (h, d) in branches if d >= d_min], key=lambda x: x[0]
    )
    notes = [
        f"effective d_min = {d_min:.1f} cm (baseline {p.d_min_cm} cm scaled by weight)",
        f"R0 = alpha*h = {p.ground_reach_m:.2f} m; mount margin = {p.mount_margin_m} m",
        f"allowed inter-branch gap = {p.allowed_gap_m():.2f} m",
    ]

    if not load_bearing:
        return ReachResult(
            mode="measured_ladder",
            is_measured_ladder=True,
            reachable=False,
            reachable_height_m=None,
            plausibility=None,
            confidence=round(ladder_confidence, 3),
            effective_d_min_cm=d_min,
            notes=notes + ["no branch meets the load-bearing diameter threshold"],
        )

    # Mount: lowest load-bearing branch must be within ground reach + margin.
    mount_ceiling = p.ground_reach_m + p.mount_margin_m
    if load_bearing[0][0] > mount_ceiling:
        return ReachResult(
            mode="measured_ladder",
            is_measured_ladder=True,
            reachable=False,
            reachable_height_m=None,
            plausibility=None,
            confidence=round(ladder_confidence, 3),
            effective_d_min_cm=d_min,
            notes=notes
            + [
                f"lowest load-bearing branch at {load_bearing[0][0]:.2f} m exceeds "
                f"mount ceiling {mount_ceiling:.2f} m"
            ],
        )

    # Ladder: walk upward while consecutive gaps stay within the allowed gap.
    gap = p.allowed_gap_m()
    ladder = [{"height_m": load_bearing[0][0], "diameter_cm": load_bearing[0][1]}]
    reach_h = load_bearing[0][0]
    for h, d in load_bearing[1:]:
        if h - reach_h <= gap:
            ladder.append({"height_m": h, "diameter_cm": d})
            reach_h = h
        else:
            break  # ladder broken

    return ReachResult(
        mode="measured_ladder",
        is_measured_ladder=True,
        reachable=True,
        reachable_height_m=round(reach_h, 2),
        ladder=ladder,
        plausibility=None,
        confidence=0.9,
        effective_d_min_cm=d_min,
        notes=notes + [f"retained ladder of {len(ladder)} branch(es)"],
    )


def _form_based_guess(
    scaffold_form: Optional[float],
    f_dbh: Optional[float],
    p: ReachParams,
    dbh_estimated: bool,
) -> ReachResult:
    """DEGRADATION path (v1): no branch data -> species-form + DBH plausibility.

    This is explicitly a GUESS about whether this species at this trunk size
    *typically* offers a low, climbable scaffold. It is NOT a measured ladder and
    emits no branch heights, no H, and no load rating.
    """
    notes = [
        "NO per-branch data available (Tier C not wired in v1).",
        "This is a FORM-BASED GUESS from species scaffold-form + trunk size, "
        "NOT a measured branch ladder.",
        f"effective d_min = {p.effective_d_min_cm:.1f} cm would apply if branch "
        "data existed.",
    ]

    if scaffold_form is None and f_dbh is None:
        return ReachResult(
            mode="form_based_guess",
            is_measured_ladder=False,
            reachable=False,
            reachable_height_m=None,
            plausibility=None,
            confidence=0.05,
            effective_d_min_cm=p.effective_d_min_cm,
            notes=notes + ["neither species form nor size known — cannot even guess"],
        )

    form = scaffold_form if scaffold_form is not None else 0.4
    size = f_dbh if f_dbh is not None else 0.3
    # Weight scaffold form more heavily: whether a low reachable scaffold exists
    # is dominated by crown architecture, not girth.
    plausibility = round(0.65 * form + 0.35 * size, 4)

    # Confidence for a form-based guess is intrinsically low and capped hard.
    conf = 0.35
    if scaffold_form is None:
        conf -= 0.15
    if dbh_estimated:
        conf -= 0.10
    conf = max(0.05, round(conf, 3))

    return ReachResult(
        mode="form_based_guess",
        is_measured_ladder=False,
        reachable=plausibility >= 0.4,  # a soft threshold, clearly a guess
        reachable_height_m=None,
        plausibility=plausibility,
        confidence=conf,
        effective_d_min_cm=p.effective_d_min_cm,
        notes=notes,
    )


def reach_match(
    params: ReachParams,
    *,
    branches: Optional[list[tuple[float, float]]] = None,
    ladder_confidence: float = 0.9,
    scaffold_form: Optional[float] = None,
    f_dbh: Optional[float] = None,
    dbh_estimated: bool = False,
) -> ReachResult:
    """Entry point.

    If real ``branches`` [(height_m, diameter_cm), ...] are supplied (Tier C
    street CV or Premium LiDAR), run the measured mount+ladder logic — with
    ``ladder_confidence`` reflecting how much to trust those measurements (Tier C
    passes its coarse ``tierC_confidence``; Premium passes ~0.9). Otherwise (the
    v1 case) run the clearly-labelled form-based guess. The two modes are never
    conflated: ``is_measured_ladder`` and ``mode`` tell callers which ran.
    """
    if branches:
        return _measured_ladder(branches, params, ladder_confidence=ladder_confidence)
    return _form_based_guess(scaffold_form, f_dbh, params, dbh_estimated)
