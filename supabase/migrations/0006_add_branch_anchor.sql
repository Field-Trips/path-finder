-- Add branch_anchor_id to paths. A non-null branch_anchor_id means this path
-- is BRANCHED — it goes Place → Anchor → BranchAnchor → Concept instead of
-- the direct Place → Anchor → Concept.
ALTER TABLE path_finder.paths
ADD COLUMN branch_anchor_id INTEGER REFERENCES path_finder.anchors(id) ON DELETE SET NULL;

CREATE INDEX IF NOT EXISTS paths_branch_anchor_idx ON path_finder.paths(branch_anchor_id);
