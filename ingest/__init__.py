"""Ingestion: source registry + crosswalk + fetchers + normalisation.

Ports the *approach* of stevage/opentrees-data (MIT): treat OpenTrees as a
SOURCE REGISTRY + CROSSWALK LIBRARY (spec §2, §12) and re-pull from live portals
so ``captured_at`` is fresh. ``cleanTree`` is a faithful port of OpenTrees'
normalisation; ``crosswalk`` applies per-source field maps + unit conversions.
"""
