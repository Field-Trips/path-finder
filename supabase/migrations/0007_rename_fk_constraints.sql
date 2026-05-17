-- Rename foreign-key constraints to match current column names.
-- The columns were renamed in migration 0004 but the constraint names were
-- never updated. PostgREST relies on the constraint name as a "hint" for
-- embedded resource lookups, so we update them here.
ALTER TABLE path_finder.paths RENAME CONSTRAINT paths_start_node_id_fkey TO paths_place_node_id_fkey;
ALTER TABLE path_finder.paths RENAME CONSTRAINT paths_end_node_id_fkey TO paths_concept_node_id_fkey;
