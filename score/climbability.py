"""Transparent climbability score (spec §7.1).

    S = w_sp * f_species + w_db * f_dbh + w_c * f_streetcv

Design commitments (invariants #1, #2, and "no black box"):
  - It is a confidence-weighted sum of interpretable features, never an opaque
    model. Weights are module constants you can read and tune.
  - In Tier-A-only v1, w_sp and w_db dominate; the Tier C street-CV term is
    DORMANT (f_streetcv is always None, its weight is redistributed).
  - Missing features do not silently become zero: weights are renormalised over
    the features we actually have, and their absence LOWERS ``confidence``.
  - Every score carries a machine-readable ``why_scored`` trace, a ``confidence``
    in [0,1], and a ``provenance`` block naming the contributing evidence tiers.

The score RANKS candidates. It never certifies safety (invariant #1).
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import TYPE_CHECKING, Optional

from features.dbh_feature import DbhFeature, dbh_size_feature

if TYPE_CHECKING:  # avoid a hard import; Tier B is an optional pipeline stage
    from tierB.parcels import EligibilityResult
from features.species_prior import (
    SpeciesPrior,
    lookup_species_prior,
    species_feature_score,
)

# --- Base weights (tunable) ----------------------------------------------------
# These are the *design* weights. When a feature is unavailable its weight is
# redistributed proportionally across the features that are present.
W_SPECIES = 0.55
W_DBH = 0.35
W_STREETCV = 0.10  # Tier C — DORMANT in v1 (f_streetcv is always None).


@dataclass
class ScoreResult:
    score: Optional[float]           # S in [0,1], or None if no signal at all
    confidence: float                # [0,1] — how much to trust `score`
    eligible: bool = True            # Tier B gate: False -> not served (private)
    why_scored: list[dict] = field(default_factory=list)  # machine-readable trace
    provenance: dict = field(default_factory=dict)         # tiers + source + license
    features: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "score": self.score,
            "confidence": self.confidence,
            "eligible": self.eligible,
            "why_scored": self.why_scored,
            "provenance": self.provenance,
            "features": self.features,
        }


def _confidence(
    species_known: bool,
    species_match: str,
    dbh: DbhFeature,
    captured_at_fresh: Optional[bool],
) -> float:
    """Combine evidence-quality signals into a [0,1] confidence.

    Confidence is LOW when we lean on unknown species or estimated DBH, and is
    nudged by data freshness. It is deliberately conservative: in v1 the highest
    confidence attainable is well below 1.0 because the branch-ladder tier is
    entirely absent (spec §11 residual gap #1).
    """
    c = 0.0

    # Species contribution to confidence (max 0.45).
    if species_known:
        c += {"species": 0.45, "genus": 0.40, "family": 0.22}.get(species_match, 0.30)
    else:
        c += 0.05  # unknown genus: we still scored DBH, but trust is low

    # DBH contribution (max 0.35).
    if dbh.basis == "measured":
        c += 0.35
    elif dbh.basis == "height_allometry":
        c += 0.15  # estimated DBH is materially weaker evidence
    else:
        c += 0.03

    # Freshness nudge (max ~0.10).
    if captured_at_fresh is True:
        c += 0.10
    elif captured_at_fresh is False:
        c += 0.02

    # HARD CEILING: with no Tier C branch geometry, we cannot be highly confident
    # a tree is climbable. Cap Tier-A-only confidence at 0.75.
    return round(min(c, 0.75), 3)


def score_tree(
    *,
    genus: Optional[str],
    species: Optional[str] = None,
    family: Optional[str] = None,
    dbh_cm: Optional[float] = None,
    height_m: Optional[float] = None,
    captured_at_fresh: Optional[bool] = None,
    source_id: Optional[str] = None,
    source_url: Optional[str] = None,
    license_: Optional[str] = None,
    f_streetcv: Optional[float] = None,  # Tier C — stays None in v1
    tierb: Optional["EligibilityResult"] = None,  # Tier B gate + hazard penalty
) -> ScoreResult:
    """Score one tree from Tier-A fields. Pure function, no I/O.

    Returns a ScoreResult with a full why_scored trace. Passing ``f_streetcv``
    is the ONLY seam the (future) Tier C pipeline needs — everything else already
    supports it.

    ``tierb`` is the Tier B reconciliation (spec §4.2). It NEVER adds positive
    score: it only gates (private parcel -> ``eligible=False``) and applies a
    multiplicative hazard penalty (power line / road / waterway proximity).
    """
    why: list[dict] = []

    # --- f_species ------------------------------------------------------------
    prior: SpeciesPrior = lookup_species_prior(genus, species, family)
    f_species = species_feature_score(prior)
    why.append(
        {
            "feature": "species",
            "value": f_species,
            "matched_on": prior.matched_on,
            "matched_key": prior.matched_key,
            "tiers": prior.tiers,
            # numeric scaffold_form is retained so the API can run the reach-match
            # degradation path server-side without recomputing features.
            "scaffold_form": prior.scaffold_form,
            "note": (
                "genus not in curated table — species term omitted, confidence lowered"
                if f_species is None
                else "wood_strength * scaffold_form * (1 - shed_risk)"
            ),
        }
    )

    # --- f_dbh ----------------------------------------------------------------
    dbh: DbhFeature = dbh_size_feature(dbh_cm, height_m, genus)
    f_dbh = dbh.score
    why.append(
        {
            "feature": "dbh",
            "value": f_dbh,
            "basis": dbh.basis,
            "dbh_cm_used": dbh.dbh_cm_used,
            "estimated": dbh.estimated,
            "note": (
                "trunk size is a PLAUSIBILITY prior only — DBH is not branch geometry"
                + (" (DBH estimated from height)" if dbh.estimated else "")
            ),
        }
    )

    # --- f_streetcv (Tier C, dormant) ----------------------------------------
    why.append(
        {
            "feature": "streetcv",
            "value": f_streetcv,
            "note": "Tier C branch-geometry signal — DORMANT in v1 (no imagery pipeline)",
        }
    )

    # --- Confidence-weighted sum with renormalisation -------------------------
    terms: list[tuple[float, float]] = []  # (weight, value) for present features
    if f_species is not None:
        terms.append((W_SPECIES, f_species))
    terms.append((W_DBH, f_dbh))  # f_dbh is always present (falls back to 0.3)
    if f_streetcv is not None:
        terms.append((W_STREETCV, f_streetcv))

    weight_sum = sum(w for w, _ in terms)
    if weight_sum > 0:
        score = sum(w * v for w, v in terms) / weight_sum
        score = round(max(0.0, min(1.0, score)), 4)
    else:
        score = None

    why.append(
        {
            "feature": "_aggregate",
            "value": score,
            "weights_used": {
                "w_species": W_SPECIES if f_species is not None else 0.0,
                "w_dbh": W_DBH,
                "w_streetcv": W_STREETCV if f_streetcv is not None else 0.0,
            },
            "renormalised_over": [round(w, 3) for w, _ in terms],
            "note": "confidence-weighted sum, weights renormalised over present features",
        }
    )

    confidence = _confidence(
        prior.is_known, prior.matched_on, dbh, captured_at_fresh
    )

    tiers = ["A:species_prior", "A:dbh"]
    if f_streetcv is not None:
        tiers.append("C:street_cv")

    # --- Tier B: eligibility gate + hazard penalty (never positive score) -----
    eligible = True
    tierb_prov: Optional[dict] = None
    if tierb is not None:
        tiers = tierb.tiers + tiers
        eligible = not tierb.excluded
        pre_penalty = score
        if score is not None and tierb.penalty != 1.0:
            score = round(score * tierb.penalty, 4)
        why.append(
            {
                "feature": "_tierB",
                "eligible": eligible,
                "public_flag": tierb.public_flag,
                "penalty": tierb.penalty,
                "score_before_penalty": pre_penalty,
                "score_after_penalty": score,
                "hazards": [h.__dict__ for h in tierb.hazards],
                "note": (
                    "Tier B is an eligibility GATE + hazard PENALTY only — it "
                    "adds no climbability signal (spec §4)."
                ),
            }
        )
        tierb_prov = tierb.to_dict()

    provenance = {
        "tiers": tiers,
        "source_id": source_id,
        "source_url": source_url,
        "license": license_,
        "captured_at_fresh": captured_at_fresh,
        "eligible": eligible,
        "tierB": tierb_prov,
        "disclaimer": (
            "Ranked candidate only. NOT a safety certification. Branch-ladder "
            "geometry is not measured in v1 — see reach-match form-based guess."
        ),
    }

    return ScoreResult(
        score=score,
        confidence=confidence,
        eligible=eligible,
        why_scored=why,
        provenance=provenance,
        features={
            "f_species": f_species,
            "f_dbh": f_dbh,
            "f_streetcv": f_streetcv,
            "species_prior": asdict(prior),
            "dbh_feature": asdict(dbh),
        },
    )
