-- Field Trips path-finder: add image_url to nodes
--
-- Wikipedia images are stored as Wikimedia Commons URLs (public, no CDN cost).
-- Apply in the Supabase SQL editor:
--   https://supabase.com/dashboard/project/vjikcsifkvphuiwjrmqi/sql/new

ALTER TABLE path_finder.nodes
  ADD COLUMN IF NOT EXISTS image_url TEXT;

COMMENT ON COLUMN path_finder.nodes.image_url IS
  'Main article image from Wikipedia (Wikimedia Commons URL). Null if the article has no lead image.';
