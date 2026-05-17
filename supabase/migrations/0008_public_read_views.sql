-- Public read API surface for the website.
-- Enables RLS, grants public-read on path_finder tables, and creates three
-- frontend-friendly views in the public schema (auto-exposed by PostgREST):
--
--   public.ft_anchors    — anchors + place + ready image
--   public.ft_paths      — completed paths with anchor + concept + branch info
--   public.ft_path_hops  — ordered hops per path, with node titles/images/types
--
-- Views use security_invoker=true so they respect RLS on the underlying tables.
-- The Supabase anon key (read-only) can safely query these views.

ALTER TABLE path_finder.anchors ENABLE ROW LEVEL SECURITY;

CREATE POLICY "public read" ON path_finder.nodes   FOR SELECT USING (true);
CREATE POLICY "public read" ON path_finder.anchors FOR SELECT USING (true);
CREATE POLICY "public read" ON path_finder.paths   FOR SELECT USING (true);
CREATE POLICY "public read" ON path_finder.edges   FOR SELECT USING (true);

CREATE OR REPLACE VIEW public.ft_anchors WITH (security_invoker=true) AS
SELECT
  a.id,
  a.rationale,
  COALESCE(a.custom_image_url, n.image_url) AS image_url,
  n.title         AS title,
  n.wikipedia_url AS wikipedia_url,
  n.node_type     AS node_type,
  n.intro_text    AS intro_text,
  p.id            AS place_id,
  p.title         AS place_title,
  p.wikipedia_url AS place_wikipedia_url
FROM path_finder.anchors a
JOIN path_finder.nodes n ON a.node_id = n.id
JOIN path_finder.nodes p ON a.place_node_id = p.id;

CREATE OR REPLACE VIEW public.ft_paths WITH (security_invoker=true) AS
SELECT
  p.id,
  p.theme,
  p.narrative,
  p.total_hops,
  p.created_at,
  place_n.id      AS place_id,
  place_n.title   AS place_title,
  a.id            AS anchor_id,
  anchor_n.title  AS anchor_title,
  COALESCE(a.custom_image_url, anchor_n.image_url) AS anchor_image_url,
  concept_n.id            AS concept_id,
  concept_n.title         AS concept_title,
  concept_n.wikipedia_url AS concept_wikipedia_url,
  concept_n.node_type     AS concept_node_type,
  concept_n.intro_text    AS concept_intro_text,
  concept_n.image_url     AS concept_image_url,
  branch_a.id            AS branch_anchor_id,
  branch_n.title         AS branch_anchor_title,
  COALESCE(branch_a.custom_image_url, branch_n.image_url) AS branch_anchor_image_url,
  (p.branch_anchor_id IS NOT NULL) AS is_branched
FROM path_finder.paths p
JOIN path_finder.nodes place_n   ON p.place_node_id    = place_n.id
JOIN path_finder.anchors a       ON p.anchor_id        = a.id
JOIN path_finder.nodes anchor_n  ON a.node_id          = anchor_n.id
JOIN path_finder.nodes concept_n ON p.concept_node_id  = concept_n.id
LEFT JOIN path_finder.anchors branch_a ON p.branch_anchor_id = branch_a.id
LEFT JOIN path_finder.nodes branch_n   ON branch_a.node_id   = branch_n.id
WHERE p.completed = true;

CREATE OR REPLACE VIEW public.ft_path_hops WITH (security_invoker=true) AS
SELECT
  e.path_id,
  e.position_in_path,
  e.from_node_id,
  from_n.title         AS from_title,
  from_n.wikipedia_url AS from_wikipedia_url,
  from_n.image_url     AS from_image_url,
  from_n.node_type     AS from_node_type,
  e.to_node_id,
  to_n.title           AS to_title,
  to_n.wikipedia_url   AS to_wikipedia_url,
  to_n.image_url       AS to_image_url,
  to_n.node_type       AS to_node_type
FROM path_finder.edges e
JOIN path_finder.nodes from_n ON e.from_node_id = from_n.id
JOIN path_finder.nodes to_n   ON e.to_node_id   = to_n.id;

GRANT SELECT ON public.ft_anchors   TO anon, authenticated;
GRANT SELECT ON public.ft_paths     TO anon, authenticated;
GRANT SELECT ON public.ft_path_hops TO anon, authenticated;
