-- Anchor architecture: paths now go Place → Anchor → Concept.
-- The Anchor (a curated person/place/thing pinned on the map) is the
-- waypoint in the middle; the Place is the start, the Concept is the end.

BEGIN;

-- Wipe existing data — old paths went Object → Place and don't fit the new model.
DELETE FROM path_finder.edges;
DELETE FROM path_finder.paths;
DELETE FROM path_finder.nodes;

-- New anchors table: curated objects on a place.
CREATE TABLE IF NOT EXISTS path_finder.anchors (
    id                SERIAL PRIMARY KEY,
    node_id           INTEGER NOT NULL REFERENCES path_finder.nodes(id) ON DELETE CASCADE,
    place_node_id     INTEGER NOT NULL REFERENCES path_finder.nodes(id) ON DELETE CASCADE,
    rationale         TEXT,
    custom_image_url  TEXT,
    created_at        TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE(node_id, place_node_id)
);

CREATE INDEX IF NOT EXISTS anchors_place_idx ON path_finder.anchors(place_node_id);

-- Rename paths columns to reflect the new semantics.
ALTER TABLE path_finder.paths RENAME COLUMN start_node_id TO place_node_id;
ALTER TABLE path_finder.paths RENAME COLUMN end_node_id   TO concept_node_id;

-- Add anchor_id (the middle waypoint).
ALTER TABLE path_finder.paths
    ADD COLUMN anchor_id INTEGER REFERENCES path_finder.anchors(id) ON DELETE SET NULL;

-- Drop representative_node_id — the Anchor is the representative now.
ALTER TABLE path_finder.paths DROP COLUMN IF EXISTS representative_node_id;

CREATE INDEX IF NOT EXISTS paths_anchor_idx ON path_finder.paths(anchor_id);

COMMIT;
