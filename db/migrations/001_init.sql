-- Climbable-Trees Mapping — v1 (Tier A) schema.
-- Requires PostGIS. H3 values are computed in Python and stored as text so the
-- schema does not depend on the (optional) h3-pg extension.

CREATE EXTENSION IF NOT EXISTS postgis;
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";

-- Normalised trees table (spec §2 schema, verbatim fields + score columns).
CREATE TABLE IF NOT EXISTS trees (
    tree_id      uuid PRIMARY KEY DEFAULT uuid_generate_v4(),
    geom         geometry(Point, 4326) NOT NULL,
    source_id    text NOT NULL,
    source_ref   text,
    scientific   text,
    genus        text,
    species      text,
    common       text,
    dbh_cm       real,          -- nullable (~half of rows)
    height_m     real,          -- nullable (~40% of rows)
    crown_m      real,
    health       text,
    maturity     text,
    public_flag  boolean NOT NULL DEFAULT true,
    captured_at  date,
    -- Tier A scoring, stored per-tree so the API never recomputes features.
    score        real,
    confidence   real,
    why_scored   jsonb,         -- machine-readable scoring trace
    provenance   jsonb,         -- {tiers, source_url, license, ...}
    -- H3 bucket columns for cheap viewport aggregation (multiple resolutions).
    h3_r8        text,
    h3_r10       text,
    ingested_at  timestamptz NOT NULL DEFAULT now()
);

-- Exact-dedup guard: one row per (source_id, source_ref).
CREATE UNIQUE INDEX IF NOT EXISTS trees_source_uidx
    ON trees (source_id, source_ref)
    WHERE source_ref IS NOT NULL;

-- Spatial index for viewport / radius queries (spec §8).
CREATE INDEX IF NOT EXISTS trees_geom_gist ON trees USING gist (geom);

-- H3 bucket indexes for aggregation.
CREATE INDEX IF NOT EXISTS trees_h3_r8_idx  ON trees (h3_r8);
CREATE INDEX IF NOT EXISTS trees_h3_r10_idx ON trees (h3_r10);

-- Score index to support "top candidates" ordering within a viewport.
CREATE INDEX IF NOT EXISTS trees_score_idx ON trees (score DESC);

-- Correction / label queue fed by the frontend report control (spec §8).
-- Serves (a) takedown/correction and (b) future learn-to-rank labels.
CREATE TABLE IF NOT EXISTS reports (
    report_id    uuid PRIMARY KEY DEFAULT uuid_generate_v4(),
    tree_id      uuid REFERENCES trees(tree_id) ON DELETE SET NULL,
    kind         text NOT NULL,     -- 'correction' | 'takedown' | 'label'
    payload      jsonb,             -- free-form: proposed species, note, rating
    created_at   timestamptz NOT NULL DEFAULT now(),
    resolved     boolean NOT NULL DEFAULT false
);

CREATE INDEX IF NOT EXISTS reports_tree_idx ON reports (tree_id);
CREATE INDEX IF NOT EXISTS reports_unresolved_idx ON reports (resolved) WHERE resolved = false;
