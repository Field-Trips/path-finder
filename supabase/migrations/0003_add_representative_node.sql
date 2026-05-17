-- Add representative_node_id to paths table.
-- This points to the person/place/thing along a path that gets visually
-- represented on the map (e.g. Rockwell Kent for a Marxism → Monhegan path).
ALTER TABLE path_finder.paths
ADD COLUMN representative_node_id INTEGER REFERENCES path_finder.nodes(id);
