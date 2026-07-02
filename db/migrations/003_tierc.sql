-- Tier C (spec §5): street-level geometry cross-check + coarse branch ladder.
-- Additive/idempotent. Branch outputs are the least-supported in the system, so
-- they are stored alongside tierc_confidence and always surfaced with it.

ALTER TABLE trees ADD COLUMN IF NOT EXISTS dbh_cm_streetcv   real;   -- + band in tierc jsonb
ALTER TABLE trees ADD COLUMN IF NOT EXISTS lowest_branch_h_m real;   -- COARSE
ALTER TABLE trees ADD COLUMN IF NOT EXISTS branch_ladder     jsonb;  -- [{height_m, est_diameter_cm, confidence}]
ALTER TABLE trees ADD COLUMN IF NOT EXISTS tierc_confidence  real;
ALTER TABLE trees ADD COLUMN IF NOT EXISTS f_streetcv        real;   -- Tier C climbability contribution (gated)
ALTER TABLE trees ADD COLUMN IF NOT EXISTS mly_image_id      text;
ALTER TABLE trees ADD COLUMN IF NOT EXISTS tierc             jsonb;  -- full TierCOutput incl. Mapillary attribution

-- Serve the Mapillary attribution with any thumbnail (CC-BY-SA 4.0, spec §5.1).
COMMENT ON COLUMN trees.tierc IS
  'TierCOutput JSON. If a thumbnail is displayed, tierc->attribution MUST be shown.';
