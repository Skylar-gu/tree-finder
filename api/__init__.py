"""FastAPI serving layer (spec §8).

Viewport/radius query accepts body params (h, weight, delta, d_min); the
reach-match runs server-side per request against stored features — no feature
recompute. Confidence + provenance + why_scored travel with every tree so the
frontend can render honesty (invariant #2).
"""
