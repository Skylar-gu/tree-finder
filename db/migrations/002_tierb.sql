-- Tier B (spec §4): aerial detection provenance + eligibility/hazard columns.
-- Additive and idempotent; v1 rows keep working (public_flag already exists).

-- Was this tree found by aerial crown detection (no inventory) vs. inventoried?
ALTER TABLE trees ADD COLUMN IF NOT EXISTS detected boolean NOT NULL DEFAULT false;

-- Reconciliation results. eligible=false rows are gated out of serving.
ALTER TABLE trees ADD COLUMN IF NOT EXISTS eligible boolean NOT NULL DEFAULT true;

-- Hazard proximities [{kind, distance_m, penalty}] and the applied penalty.
ALTER TABLE trees ADD COLUMN IF NOT EXISTS hazards jsonb;
ALTER TABLE trees ADD COLUMN IF NOT EXISTS tierb_penalty real;

-- The API serves only eligible trees; index to keep that filter cheap.
CREATE INDEX IF NOT EXISTS trees_eligible_idx ON trees (eligible) WHERE eligible = true;
CREATE INDEX IF NOT EXISTS trees_detected_idx ON trees (detected);
