-- Add narrative column to paths.
-- `theme` stays as a short tag/phrase. `narrative` holds a 2–3 paragraph
-- Curtis/Burke-style explanation of how the path actually connects.
ALTER TABLE path_finder.paths
ADD COLUMN narrative TEXT;
