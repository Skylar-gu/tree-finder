"""Species -> wood/form prior (spec §3.1).

Maps a tree's genus (with optional species override, family fallback) to three
coarse qualitative traits in [0,1]:

  - wood_strength : relative green-wood soundness / resistance to breakage.
  - scaffold_form : does the typical crown offer low, well-spaced, near-horizontal
                    scaffold limbs a person could ladder up?
  - shed_risk     : propensity to self-prune / summer limb-drop (higher = worse).

These are PRIORS, not measurements. wood_strength is None when the genus is not
in the curated table — callers must treat None as "unknown" (lowers confidence),
NOT as zero. See features/species_data.py for the sourcing rationale.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

from .species_data import (
    FAMILY_TRAITS,
    GENUS_TRAITS,
    SCAFFOLD_FORM_TIERS,
    SHED_RISK_TIERS,
    WOOD_STRENGTH_TIERS,
)


@dataclass
class SpeciesPrior:
    """Result of a species-prior lookup.

    Any of the three scores may be None when we have no basis to assign a tier.
    None propagates to the confidence machinery downstream; it is never silently
    coerced to a number.
    """

    wood_strength: Optional[float]
    scaffold_form: Optional[float]
    shed_risk: Optional[float]
    # Provenance of the lookup so why_scored can be honest about how coarse it is.
    matched_on: str  # "species" | "genus" | "family" | "none"
    matched_key: Optional[str]
    tiers: dict = field(default_factory=dict)

    @property
    def is_known(self) -> bool:
        return self.wood_strength is not None


def _tiers_to_prior(
    wood_tier: str, form_tier: str, shed_tier: str, matched_on: str, matched_key: str
) -> SpeciesPrior:
    return SpeciesPrior(
        wood_strength=WOOD_STRENGTH_TIERS[wood_tier],
        scaffold_form=SCAFFOLD_FORM_TIERS[form_tier],
        shed_risk=SHED_RISK_TIERS[shed_tier],
        matched_on=matched_on,
        matched_key=matched_key,
        tiers={
            "wood_strength": wood_tier,
            "scaffold_form": form_tier,
            "shed_risk": shed_tier,
        },
    )


def _norm(s: Optional[str]) -> Optional[str]:
    if not s:
        return None
    s = s.strip().lower()
    return s or None


def lookup_species_prior(
    genus: Optional[str],
    species: Optional[str] = None,
    family: Optional[str] = None,
) -> SpeciesPrior:
    """Look up traits with precedence: species override > genus > family > unknown.

    A species override key is "<genus>_<species>" (e.g. ``acer_saccharinum``),
    matching how a handful of ecologically distinct species are keyed in the
    curated table. Bare genus is tried next, then family, then we return an
    all-None "unknown" prior.
    """
    g = _norm(genus)
    sp = _norm(species)
    fam = _norm(family)

    # 1. species-specific override
    if g and sp:
        key = f"{g}_{sp}"
        if key in GENUS_TRAITS:
            return _tiers_to_prior(*GENUS_TRAITS[key], "species", key)

    # 2. genus
    if g and g in GENUS_TRAITS:
        return _tiers_to_prior(*GENUS_TRAITS[g], "genus", g)

    # 3. family fallback
    if fam and fam in FAMILY_TRAITS:
        return _tiers_to_prior(*FAMILY_TRAITS[fam], "family", fam)

    # 4. unknown — wood_strength None lowers confidence, does not zero the score.
    return SpeciesPrior(
        wood_strength=None,
        scaffold_form=None,
        shed_risk=None,
        matched_on="none",
        matched_key=None,
        tiers={},
    )


def species_feature_score(prior: SpeciesPrior) -> Optional[float]:
    """Collapse the prior into a single f_species in [0,1] for the weighted sum.

    f_species = wood_strength * scaffold_form * (1 - shed_risk)

    A multiplicative form is used deliberately: a tree that is structurally sound
    but has no low scaffold (excurrent conifer) should score low, and vice-versa.
    Returns None when the genus is unknown so climbability.py can down-weight it
    rather than inventing a value.
    """
    if not prior.is_known:
        return None
    # scaffold_form / shed_risk are always populated alongside wood_strength in
    # the curated table, but guard defensively.
    form = prior.scaffold_form if prior.scaffold_form is not None else 0.5
    shed = prior.shed_risk if prior.shed_risk is not None else 0.35
    score = prior.wood_strength * form * (1.0 - shed)
    return max(0.0, min(1.0, score))
