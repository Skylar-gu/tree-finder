"""Faithful port of OpenTrees ``cleanTree`` normalisation (spec §2, §12).

Reference: stevage/opentrees-data (MIT), primarily ``conform.js`` /
``cleanTree`` helpers. Ported behaviours:

  1. Genus/species split from a scientific name string (handles "Genus species
     'Cultivar'", hybrids "Genus x species", trailing authorities).
  2. Trim + collapse whitespace; title-case the genus, lower-case the species.
  3. Prune "not-a-tree" placeholder rows: vacant site, stump, removed, dead,
     empty planting site, etc. -> the whole record is dropped.
  4. Null out unknown / non-committal species tokens ("unknown", "spp", "sp.",
     "other", "mixed", "various", "unidentified") rather than storing garbage.

This is intentionally conservative: when in doubt we NULL a field rather than
invent a value, matching OpenTrees behaviour and design invariant #2 (honesty).
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Optional

# Rows whose species/common/description match these -> the record is NOT a tree.
# Ported from OpenTrees' vacant/removed/stump pruning.
_DROP_TOKENS = {
    "vacant",
    "vacant site",
    "vacant planting site",
    "empty",
    "empty pit",
    "empty tree pit",
    "planting site",
    "stump",
    "stump grind",
    "removed",
    "dead",
    "dead tree",
    "dead - removed",
    "gone",
    "none",
    "no tree",
    "not planted",
    "unplanted",
    "space",
    "vacant/removed",
}

# Species tokens that carry no taxonomic information -> null the species.
_UNKNOWN_SPECIES_TOKENS = {
    "unknown",
    "unidentified",
    "unk",
    "sp",
    "sp.",
    "spp",
    "spp.",
    "species",
    "other",
    "mixed",
    "various",
    "misc",
    "miscellaneous",
    "hybrid",
    "cultivar",
    "n/a",
    "na",
    "none",
    "-",
    "?",
}

# Genus tokens that are actually non-committal -> null genus too.
_UNKNOWN_GENUS_TOKENS = {
    "unknown",
    "unidentified",
    "other",
    "mixed",
    "various",
    "misc",
    "n/a",
    "na",
    "none",
    "-",
    "?",
}

_WS = re.compile(r"\s+")
_AUTHORITY = re.compile(r"\s*\(.*?\)\s*")  # drop "(L.)" style authorities
_QUOTED = re.compile(r"['\"].*?['\"]")     # drop 'Cultivar' names
_NON_ALPHA = re.compile(r"[^a-zA-Z\-\s×x]")


@dataclass
class CleanedName:
    scientific: Optional[str]
    genus: Optional[str]
    species: Optional[str]
    dropped: bool  # True -> record should be discarded entirely


def _collapse(s: Optional[str]) -> Optional[str]:
    if s is None:
        return None
    s = _WS.sub(" ", s.strip())
    return s or None


def is_drop_row(*values: Optional[str]) -> bool:
    """True if any provided field marks this as a vacant/removed/stump row."""
    for v in values:
        v = _collapse(v)
        if v and v.strip().lower() in _DROP_TOKENS:
            return True
    return False


def clean_tree_name(
    scientific: Optional[str] = None,
    genus: Optional[str] = None,
    species: Optional[str] = None,
    common: Optional[str] = None,
) -> CleanedName:
    """Normalise taxonomic fields the way OpenTrees ``cleanTree`` does.

    Precedence: an explicit ``scientific`` string is parsed into genus/species;
    otherwise pre-split ``genus``/``species`` are cleaned directly.
    """
    # Drop the whole record if any field flags a non-tree placeholder.
    if is_drop_row(scientific, genus, species, common):
        return CleanedName(None, None, None, dropped=True)

    sci = _collapse(scientific)
    g = _collapse(genus)
    sp = _collapse(species)

    # If we have a scientific string, parse genus/species out of it.
    if sci:
        cleaned = _AUTHORITY.sub(" ", sci)
        cleaned = _QUOTED.sub(" ", cleaned)
        cleaned = _NON_ALPHA.sub(" ", cleaned)
        cleaned = _collapse(cleaned)
        if cleaned:
            parts = cleaned.split(" ")
            # Handle hybrid marker "Genus x species" / "Genus × species".
            if len(parts) >= 3 and parts[1].lower() in ("x", "×"):
                g = g or parts[0]
                sp = sp or parts[2]
            else:
                g = g or parts[0]
                if len(parts) >= 2:
                    sp = sp or parts[1]

    # Normalise genus: title-case; null if non-committal.
    if g:
        g_token = g.strip().lower()
        if g_token in _UNKNOWN_GENUS_TOKENS:
            g = None
        else:
            g = g.strip().capitalize()

    # Normalise species: lower-case single epithet; null if non-committal.
    if sp:
        sp_token = sp.strip().lower().rstrip(".")
        first = sp_token.split(" ")[0]
        if first in _UNKNOWN_SPECIES_TOKENS or sp_token in _UNKNOWN_SPECIES_TOKENS:
            sp = None
        else:
            sp = first  # keep the epithet only, drop cultivar/authority remnants

    # Rebuild a clean scientific string from the parts we trust.
    if g and sp:
        rebuilt = f"{g} {sp}"
    elif g:
        rebuilt = g
    else:
        rebuilt = None

    return CleanedName(scientific=rebuilt, genus=g, species=sp, dropped=False)
