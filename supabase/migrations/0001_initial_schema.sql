-- Field Trips path-finder: initial schema
--
-- All path-finder tables live in a dedicated `path_finder` Postgres schema,
-- not in `public`. The Field Trips Supabase project already has tables in
-- `public` (from book-ingest), so we namespace ours to avoid any collision
-- and to keep the data architecture self-documenting.
--
-- THREE TABLES + ONE VIEW:
--   path_finder.nodes        every Wikipedia page we have touched (typed)
--   path_finder.paths        each rabbit-hole session
--   path_finder.edges        each hop within a path
--   path_finder.connections  view: deduped (from, to) across all paths
--
-- HOW TO APPLY:
--   Easiest path: paste this whole file into the Supabase SQL editor
--   (https://supabase.com/dashboard/project/vjikcsifkvphuiwjrmqi/sql/new)
--   and click Run.
--
--   Or via CLI: `supabase db push` from the path-finder directory after
--   linking the project.
--
-- AFTER APPLYING, ONE MORE STEP:
--   Supabase only exposes the `public` schema through its REST API by default.
--   We don't strictly need REST access (the script uses the Python client),
--   but if you want to query path_finder tables through the Supabase REST API
--   or Table Editor:
--     Project Settings → API → "Exposed schemas" → add "path_finder" → Save
--   Without this, the dashboard Table Editor won't show our tables. The Python
--   client will still work either way because it connects through PostgREST
--   with the schema set explicitly.

CREATE SCHEMA IF NOT EXISTS path_finder;

-- ---------------------------------------------------------------------------
-- nodes
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS path_finder.nodes (
  id                  BIGSERIAL PRIMARY KEY,
  wikipedia_url       TEXT NOT NULL UNIQUE,
  title               TEXT NOT NULL,
  node_type           TEXT CHECK (node_type IN ('place', 'idea', 'person', 'event', 'thing')),
  located_in          BIGINT REFERENCES path_finder.nodes(id) ON DELETE SET NULL,
  is_monhegan_object  BOOLEAN NOT NULL DEFAULT FALSE,
  intro_text          TEXT,          -- first paragraph of the article, useful for downstream display
  coordinates         POINT,         -- nullable; only populated for physical places
  created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_nodes_node_type   ON path_finder.nodes (node_type);
CREATE INDEX IF NOT EXISTS idx_nodes_located_in  ON path_finder.nodes (located_in);
CREATE INDEX IF NOT EXISTS idx_nodes_monhegan    ON path_finder.nodes (is_monhegan_object) WHERE is_monhegan_object;
CREATE INDEX IF NOT EXISTS idx_nodes_title_lower ON path_finder.nodes (LOWER(title));

COMMENT ON TABLE  path_finder.nodes IS 'Every Wikipedia page we have touched, with type tag and optional grounding.';
COMMENT ON COLUMN path_finder.nodes.located_in IS 'Self-referential FK. Example: Monhegan Lighthouse located_in Monhegan Island.';
COMMENT ON COLUMN path_finder.nodes.is_monhegan_object IS 'True for the v0 anchor set (lighthouse, art colony, tick eradication, etc.).';
COMMENT ON COLUMN path_finder.nodes.intro_text IS 'First paragraph from Wikipedia. Captured at node creation for context.';
COMMENT ON COLUMN path_finder.nodes.coordinates IS 'lat/long for physical places; left null for ideas/events/etc.';

-- ---------------------------------------------------------------------------
-- paths
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS path_finder.paths (
  id                  BIGSERIAL PRIMARY KEY,
  start_node_id       BIGINT NOT NULL REFERENCES path_finder.nodes(id),
  end_node_id         BIGINT NOT NULL REFERENCES path_finder.nodes(id),
  total_hops          INT NOT NULL,
  theme               TEXT,          -- short auto-generated label, e.g. "via wildlife management"
  completed           BOOLEAN NOT NULL DEFAULT TRUE,  -- false if path hit the hop cap before reaching end
  permutation_group   TEXT,          -- groups multiple paths with the same start/end
  created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_paths_start ON path_finder.paths (start_node_id);
CREATE INDEX IF NOT EXISTS idx_paths_end   ON path_finder.paths (end_node_id);
CREATE INDEX IF NOT EXISTS idx_paths_group ON path_finder.paths (permutation_group);

COMMENT ON TABLE  path_finder.paths IS 'One row per rabbit-hole session. Multiple permutations of the same start/end share a permutation_group.';
COMMENT ON COLUMN path_finder.paths.permutation_group IS 'Free-text label used to group permutations. Convention: "<start_slug>__<end_slug>".';
COMMENT ON COLUMN path_finder.paths.completed IS 'False if the agent ran out of hops before reaching end_node.';
COMMENT ON COLUMN path_finder.paths.total_hops IS 'Number of edges in this path (node-to-node transitions). A 4-node path has total_hops = 3.';

-- ---------------------------------------------------------------------------
-- edges
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS path_finder.edges (
  id                  BIGSERIAL PRIMARY KEY,
  path_id             BIGINT NOT NULL REFERENCES path_finder.paths(id) ON DELETE CASCADE,
  from_node_id        BIGINT NOT NULL REFERENCES path_finder.nodes(id),
  to_node_id          BIGINT NOT NULL REFERENCES path_finder.nodes(id),
  position_in_path    INT NOT NULL,
  UNIQUE (path_id, position_in_path)
);

CREATE INDEX IF NOT EXISTS idx_edges_path ON path_finder.edges (path_id);
CREATE INDEX IF NOT EXISTS idx_edges_from ON path_finder.edges (from_node_id);
CREATE INDEX IF NOT EXISTS idx_edges_to   ON path_finder.edges (to_node_id);

COMMENT ON TABLE  path_finder.edges IS 'Each hop within a path. Path-scoped: the same (from, to) can exist in many paths.';
COMMENT ON COLUMN path_finder.edges.position_in_path IS 'Zero-indexed position. position=0 means from_node_id is the path start.';

-- ---------------------------------------------------------------------------
-- handy view: global connections (dedupes (from, to) across all paths)
-- ---------------------------------------------------------------------------
CREATE OR REPLACE VIEW path_finder.connections AS
SELECT
  e.from_node_id,
  e.to_node_id,
  COUNT(*) AS path_count,
  ARRAY_AGG(DISTINCT e.path_id) AS path_ids
FROM path_finder.edges e
GROUP BY e.from_node_id, e.to_node_id;

COMMENT ON VIEW path_finder.connections IS 'Deduped from→to relationships across all paths, with the list of paths each appears in.';

-- ---------------------------------------------------------------------------
-- permissions
-- ---------------------------------------------------------------------------
-- service_role: full read/write — used by the path-finder script (server-side).
-- anon + authenticated: read-only — so Jeremy's website can query this data
-- from the browser using the publishable anon key. The data is sourced from
-- Wikipedia (public information), so making it world-readable is intentional.
-- If you ever store anything sensitive here, drop the anon grant and add RLS.
GRANT USAGE ON SCHEMA path_finder TO service_role, anon, authenticated;
GRANT ALL ON ALL TABLES IN SCHEMA path_finder TO service_role;
GRANT ALL ON ALL SEQUENCES IN SCHEMA path_finder TO service_role;
GRANT SELECT ON ALL TABLES IN SCHEMA path_finder TO anon, authenticated;

-- defaults so future tables in this schema inherit the same grants
ALTER DEFAULT PRIVILEGES IN SCHEMA path_finder GRANT ALL ON TABLES TO service_role;
ALTER DEFAULT PRIVILEGES IN SCHEMA path_finder GRANT ALL ON SEQUENCES TO service_role;
ALTER DEFAULT PRIVILEGES IN SCHEMA path_finder GRANT SELECT ON TABLES TO anon, authenticated;
