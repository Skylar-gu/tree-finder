from ingest.clean_tree import clean_tree_name, is_drop_row


def test_genus_species_split_from_scientific():
    r = clean_tree_name(scientific="Quercus rubra")
    assert r.genus == "Quercus"
    assert r.species == "rubra"
    assert r.scientific == "Quercus rubra"
    assert not r.dropped


def test_strips_authority_and_cultivar():
    r = clean_tree_name(scientific="Acer platanoides (L.) 'Crimson King'")
    assert r.genus == "Acer"
    assert r.species == "platanoides"


def test_hybrid_marker():
    r = clean_tree_name(scientific="Platanus x acerifolia")
    assert r.genus == "Platanus"
    assert r.species == "acerifolia"


def test_double_colon_common_suffix():
    # SF-style "Genus species :: Common name"
    r = clean_tree_name(scientific="Tristaniopsis laurina :: Swamp Myrtle")
    assert r.genus == "Tristaniopsis"
    assert r.species == "laurina"


def test_prune_vacant_removed_stump():
    for bad in ["Vacant Site", "STUMP", "removed", "dead", "None"]:
        r = clean_tree_name(scientific=bad)
        assert r.dropped, bad
    assert is_drop_row(None, "stump", None)


def test_null_unknown_species():
    r = clean_tree_name(genus="Quercus", species="sp.")
    assert r.genus == "Quercus"
    assert r.species is None


def test_null_unknown_genus():
    r = clean_tree_name(genus="Unknown", species="foo")
    assert r.genus is None


def test_species_epithet_only_drops_cultivar_words():
    r = clean_tree_name(genus="Malus", species="domestica Honeycrisp")
    assert r.species == "domestica"
