from features.species_prior import (
    lookup_species_prior,
    species_feature_score,
)


def test_strong_oak_beats_brittle_willow():
    oak = species_feature_score(lookup_species_prior("Quercus"))
    willow = species_feature_score(lookup_species_prior("Salix"))
    assert oak is not None and willow is not None
    assert oak > willow


def test_species_override_silver_maple_is_worse_than_generic_acer():
    generic = species_feature_score(lookup_species_prior("Acer"))
    silver = species_feature_score(lookup_species_prior("Acer", "saccharinum"))
    assert silver < generic  # limb-drop + weaker wood


def test_excurrent_conifer_scores_low_despite_ok_wood():
    fir = lookup_species_prior("Pseudotsuga")
    assert fir.is_known
    # very_poor scaffold form should drag the multiplicative score down
    assert species_feature_score(fir) < 0.3


def test_unknown_genus_returns_none_not_zero():
    prior = lookup_species_prior("Notarealgenus")
    assert prior.wood_strength is None
    assert not prior.is_known
    assert species_feature_score(prior) is None


def test_family_fallback():
    prior = lookup_species_prior("Weirდgenus", family="Fagaceae")
    assert prior.matched_on == "family"
    assert prior.is_known


def test_scores_bounded():
    for g in ["Quercus", "Salix", "Pinus", "Platanus", "Eucalyptus"]:
        s = species_feature_score(lookup_species_prior(g))
        assert 0.0 <= s <= 1.0
