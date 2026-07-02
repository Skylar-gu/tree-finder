"""Transparent scoring + reach-match.

Nothing here is a black box. climbability.py emits a written ``why_scored``
trace, a ``confidence`` value and a ``provenance`` block for every tree. reach.py
runs the mount+ladder logic when branch data exists — in v1 it never does, so it
runs the explicitly-labelled DEGRADATION path (a form-based guess, never a fake
measured ladder).
"""
