"""Curated genus -> qualitative climbability traits.

Design decision (spec §3.1): we do NOT fabricate species-level MOR (modulus of
rupture) numbers. Real MOR/MOE data exist only for a few hundred commercial
timbers under controlled clear-specimen tests and do not transfer to standing
open-grown urban trees. Instead we assign each genus a COARSE QUALITATIVE TIER
and map tiers to [0,1] scores. The tiers are grounded in:

  - USDA FPL Wood Handbook (FPL-GTR-282), Ch. 5 "Mechanical Properties of Wood"
    — relative green-wood strength / modulus of rupture rankings by species.
  - Global Wood Density Database (Zanne et al. 2009) — genus-level oven-dry
    wood density, a strong correlate of green MOR.
  - Common arboricultural failure literature for limb-drop / self-pruning
    behaviour (e.g. Populus, Salix, Acer saccharinum, some Eucalyptus).

The scores are deliberately coarse buckets, NOT measurements. A genus absent
from this table yields wood_strength = None, which LOWERS confidence but does
not zero the score (spec invariant: cheapest reliable signal first).
"""

from __future__ import annotations

# --- Qualitative tier -> coarse [0,1] score maps -------------------------------
# Buckets are intentionally few and evenly spaced. Do not read precision into
# the third decimal place that isn't there.

WOOD_STRENGTH_TIERS: dict[str, float] = {
    "very_strong": 0.92,   # dense, high green MOR (e.g. Carpinus, Quercus)
    "strong": 0.78,        # sound structural hardwoods (Fagus, Platanus)
    "moderate": 0.55,      # average urban hardwoods (Fraxinus, Tilia)
    "weak": 0.35,          # low-density, prone to breakage (Betula, Prunus)
    "brittle": 0.18,       # notoriously failure-prone (Salix, Populus, Ailanthus)
}

# scaffold_form: does the typical crown architecture offer LOW, near-horizontal,
# well-spaced scaffold limbs a person could ladder up? High single clear boles
# and excurrent conifers score low even if the wood is strong.
SCAFFOLD_FORM_TIERS: dict[str, float] = {
    "excellent": 0.90,   # low spreading decurrent scaffolds (open-grown oak, maple)
    "good": 0.72,         # decurrent but often higher first limb
    "moderate": 0.50,     # variable / commonly high-pruned as street trees
    "poor": 0.28,         # clear tall bole, few low limbs
    "very_poor": 0.12,    # excurrent conifer / palm / columnar — no ladder
}

# shed_risk: propensity to self-prune / summer limb-drop. HIGHER is worse; the
# prior consumes (1 - shed_risk) so a high value depresses the score.
SHED_RISK_TIERS: dict[str, float] = {
    "low": 0.10,
    "moderate": 0.35,
    "high": 0.70,
}

# --- Curated genus table -------------------------------------------------------
# (genus_lower): (wood_strength_tier, scaffold_form_tier, shed_risk_tier)
# ~130 genera spanning common temperate/urban street & park inventory taxa.
GENUS_TRAITS: dict[str, tuple[str, str, str]] = {
    # --- Strong-wood decurrent hardwoods (good climbing candidates) -----------
    "quercus":        ("very_strong", "excellent", "low"),      # oak
    "carpinus":       ("very_strong", "good",      "low"),      # hornbeam
    "fagus":          ("strong",      "good",      "low"),      # beech
    "carya":          ("very_strong", "moderate",  "moderate"), # hickory
    "ostrya":         ("very_strong", "good",      "low"),      # hophornbeam
    "platanus":       ("strong",      "excellent", "moderate"), # plane/sycamore
    "acer":           ("moderate",    "excellent", "moderate"), # maple (generic)
    "acer_saccharum": ("strong",      "excellent", "low"),      # sugar maple
    "tilia":          ("moderate",    "good",      "low"),      # linden/basswood
    "gleditsia":      ("strong",      "moderate",  "low"),      # honey locust
    "robinia":        ("strong",      "moderate",  "moderate"), # black locust
    "juglans":        ("strong",      "good",      "moderate"), # walnut
    "castanea":       ("strong",      "good",      "low"),      # chestnut
    "nyssa":          ("moderate",    "good",      "low"),      # tupelo
    "celtis":         ("moderate",    "excellent", "moderate"), # hackberry
    "ulmus":          ("moderate",    "excellent", "moderate"), # elm
    "morus":          ("moderate",    "excellent", "moderate"), # mulberry
    "maclura":        ("very_strong", "moderate",  "low"),      # osage orange
    "fraxinus":       ("moderate",    "good",      "moderate"), # ash
    "sophora":        ("moderate",    "good",      "moderate"), # pagoda tree
    "styphnolobium":  ("moderate",    "good",      "moderate"), # pagoda tree (new genus)
    "zelkova":        ("moderate",    "good",      "low"),      # zelkova
    "aesculus":       ("weak",        "excellent", "moderate"), # horse chestnut/buckeye
    "catalpa":        ("weak",        "good",      "moderate"), # catalpa
    "paulownia":      ("weak",        "moderate",  "high"),     # empress tree
    "liquidambar":    ("moderate",    "poor",      "low"),      # sweetgum (excurrent-ish)
    "liriodendron":   ("moderate",    "poor",      "moderate"), # tulip poplar (tall bole)
    "magnolia":       ("moderate",    "good",      "low"),      # magnolia
    "gymnocladus":    ("strong",      "moderate",  "low"),      # kentucky coffeetree
    "cladrastis":     ("moderate",    "good",      "moderate"), # yellowwood
    "cercis":         ("weak",        "excellent", "moderate"), # redbud (small)
    "cornus":         ("moderate",    "good",      "low"),      # dogwood (small)
    "crataegus":      ("strong",      "moderate",  "low"),      # hawthorn (small, thorny)
    "malus":          ("moderate",    "good",      "moderate"), # crabapple (small)
    "pyrus":          ("weak",        "poor",      "high"),     # callery pear (weak crotches)
    "prunus":         ("weak",        "good",      "moderate"), # cherry/plum
    "amelanchier":    ("moderate",    "moderate",  "low"),      # serviceberry (small)
    "sorbus":         ("moderate",    "moderate",  "moderate"), # mountain ash

    # --- Weak / brittle wood (poor candidates) --------------------------------
    "salix":          ("brittle",     "moderate",  "high"),     # willow
    "populus":        ("brittle",     "poor",      "high"),     # poplar/cottonwood
    "acer_saccharinum": ("weak",      "excellent", "high"),     # silver maple (limb drop)
    "ailanthus":      ("brittle",     "moderate",  "high"),     # tree of heaven
    "betula":         ("weak",        "moderate",  "moderate"), # birch
    "alnus":          ("weak",        "moderate",  "moderate"), # alder
    "acer_negundo":   ("brittle",     "moderate",  "high"),     # box elder
    "melia":          ("weak",        "moderate",  "high"),     # chinaberry
    "broussonetia":   ("weak",        "moderate",  "high"),     # paper mulberry
    "firmiana":       ("weak",        "poor",      "moderate"), # chinese parasol
    "toona":          ("weak",        "moderate",  "moderate"),

    # --- Excurrent conifers (structurally strong wood, poor ladder form) ------
    "pinus":          ("moderate",    "very_poor", "moderate"), # pine
    "picea":          ("moderate",    "very_poor", "low"),      # spruce
    "abies":          ("moderate",    "very_poor", "low"),      # fir
    "pseudotsuga":    ("strong",      "very_poor", "low"),      # douglas fir
    "tsuga":          ("moderate",    "very_poor", "low"),      # hemlock
    "cedrus":         ("moderate",    "poor",      "low"),      # true cedar (some low limbs)
    "larix":          ("moderate",    "very_poor", "low"),      # larch
    "thuja":          ("weak",        "very_poor", "low"),      # arborvitae/redcedar
    "juniperus":      ("moderate",    "poor",      "low"),      # juniper
    "chamaecyparis":  ("weak",        "very_poor", "low"),      # false cypress
    "cupressus":      ("weak",        "very_poor", "low"),      # cypress
    "taxus":          ("strong",      "poor",      "low"),      # yew (dense but shrubby)
    "sequoia":        ("moderate",    "very_poor", "low"),      # redwood
    "sequoiadendron": ("moderate",    "very_poor", "low"),      # giant sequoia
    "metasequoia":    ("weak",        "very_poor", "low"),      # dawn redwood
    "taxodium":       ("moderate",    "very_poor", "low"),      # bald cypress
    "araucaria":      ("moderate",    "very_poor", "low"),      # monkey puzzle
    "cryptomeria":    ("moderate",    "very_poor", "low"),      # japanese cedar
    "calocedrus":     ("moderate",    "very_poor", "low"),      # incense cedar
    "ginkgo":         ("moderate",    "poor",      "low"),      # ginkgo (tall, upswept)

    # --- Eucalypts & other limb-droppers --------------------------------------
    "eucalyptus":     ("moderate",    "poor",      "high"),     # gum (summer limb drop)
    "corymbia":       ("moderate",    "poor",      "high"),     # bloodwood
    "angophora":      ("moderate",    "moderate",  "high"),
    "grevillea":      ("weak",        "poor",      "moderate"),
    "callistemon":    ("weak",        "poor",      "low"),      # bottlebrush (small)
    "melaleuca":      ("weak",        "poor",      "moderate"),
    "acacia":         ("moderate",    "moderate",  "moderate"), # wattle
    "casuarina":      ("moderate",    "very_poor", "moderate"),
    "lophostemon":    ("moderate",    "poor",      "moderate"),
    "tristaniopsis":  ("moderate",    "poor",      "low"),

    # --- Palms & monocots (no scaffold ladder at all) -------------------------
    "phoenix":        ("weak",        "very_poor", "low"),      # date palm
    "washingtonia":   ("weak",        "very_poor", "low"),      # fan palm
    "arecastrum":     ("weak",        "very_poor", "low"),
    "syagrus":        ("weak",        "very_poor", "low"),      # queen palm
    "sabal":          ("weak",        "very_poor", "low"),      # palmetto
    "trachycarpus":   ("weak",        "very_poor", "low"),      # windmill palm
    "cordyline":      ("weak",        "very_poor", "low"),
    "dracaena":       ("weak",        "very_poor", "low"),

    # --- Other common street/park hardwoods -----------------------------------
    "ginkgoaceae":    ("moderate",    "poor",      "low"),
    "koelreuteria":   ("weak",        "good",      "moderate"), # golden rain tree
    "albizia":        ("weak",        "good",      "high"),     # mimosa (weak, spreading)
    "delonix":        ("weak",        "excellent", "high"),     # flame tree
    "jacaranda":      ("weak",        "good",      "moderate"),
    "tabebuia":       ("moderate",    "good",      "moderate"),
    "handroanthus":   ("strong",      "good",      "low"),      # ipê (very dense)
    "tipuana":        ("moderate",    "excellent", "moderate"),
    "brachychiton":   ("weak",        "good",      "moderate"), # bottle/flame tree
    "ficus":          ("moderate",    "excellent", "moderate"), # fig (broad low limbs)
    "olea":           ("strong",      "excellent", "low"),      # olive (dense, low, gnarled)
    "schinus":        ("weak",        "excellent", "moderate"), # pepper tree
    "pistacia":       ("moderate",    "good",      "low"),
    "cinnamomum":     ("moderate",    "excellent", "moderate"), # camphor
    "laurus":         ("moderate",    "good",      "low"),
    "arbutus":        ("moderate",    "good",      "low"),      # madrone
    "eriobotrya":     ("weak",        "good",      "low"),      # loquat
    "lagerstroemia":  ("moderate",    "excellent", "low"),      # crape myrtle (low multi-stem)
    "hibiscus":       ("weak",        "good",      "low"),
    "bauhinia":       ("weak",        "good",      "moderate"),
    "erythrina":      ("brittle",     "good",      "high"),     # coral tree (very brittle)
    "ceratonia":      ("strong",      "excellent", "low"),      # carob
    "gleditsiaceae":  ("strong",      "moderate",  "low"),
    "parkinsonia":    ("weak",        "moderate",  "moderate"), # palo verde
    "quercus_agrifolia": ("strong",   "excellent", "low"),      # coast live oak
    "quercus_virginiana": ("very_strong", "excellent", "low"),  # southern live oak (classic climber)
    "platanus_racemosa": ("strong",   "excellent", "moderate"),
    "tilia_cordata":  ("moderate",    "good",      "low"),
    "fraxinus_americana": ("strong",  "good",      "moderate"),
    "aesculus_hippocastanum": ("weak", "excellent", "moderate"),
}

# Family-level fallback when genus is unknown but family is present in provenance.
# Coarser still; used only to nudge, never to assert.
FAMILY_TRAITS: dict[str, tuple[str, str, str]] = {
    "fagaceae":     ("strong",   "good",      "low"),   # oaks, beeches, chestnuts
    "sapindaceae":  ("moderate", "excellent", "moderate"),  # maples, buckeyes
    "salicaceae":   ("brittle",  "moderate",  "high"),  # willows, poplars
    "pinaceae":     ("moderate", "very_poor", "low"),   # pines, spruces, firs
    "cupressaceae": ("weak",     "very_poor", "low"),   # cypress, junipers
    "myrtaceae":    ("moderate", "poor",      "high"),  # eucalypts
    "arecaceae":    ("weak",     "very_poor", "low"),   # palms
    "fabaceae":     ("moderate", "good",      "moderate"),  # legume trees
    "rosaceae":     ("moderate", "good",      "moderate"),  # cherries, pears, apples
    "moraceae":     ("moderate", "excellent", "moderate"),  # figs, mulberries
    "oleaceae":     ("moderate", "good",      "moderate"),  # ash, olive
    "malvaceae":    ("moderate", "good",      "low"),    # lindens, brachychiton
    "betulaceae":   ("moderate", "good",      "moderate"),  # birch, hornbeam, alder
    "bignoniaceae": ("moderate", "good",      "moderate"),  # catalpa, jacaranda
}

# Genus keys that carry a species-specific override (e.g. acer_saccharinum).
# The prior looks up "<genus>_<species>" before falling back to bare genus.
