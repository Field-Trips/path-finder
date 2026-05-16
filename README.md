# path-finder

Agentic Wikipedia path-finder for [Field Trips](https://fieldtrips.club).

Given a start and an end Wikipedia page, produces N distinct paths between them by walking the Wikipedia link graph one hop at a time, with Claude picking each next hop. Persists everything to Supabase so it can be vibe-coded into a visual product.

This is the data-collection layer of Field Trips. The product layer (Jeremy's map of Monhegan, eventually a news-to-history surface) lives in a separate repo and reads from the same Supabase.

## Status

Day 1. Scaffolded with the design, schema, CLI shape, and TODOs. The Wikipedia API + Claude-call pieces are skeletons — fill them in with Claude Code.

## How it works

1. Start with a `(start, end)` pair of Wikipedia page titles.
2. Fetch the current page's internal links via the MediaWiki API.
3. Ask Claude to pick the next hop — biased toward "plausible toward the target but non-obvious."
4. Repeat until the end is reached or a hop cap is hit.
5. For multiple permutations, run again with previously used intermediate titles added to a `forbidden` set so we get diverse routes, not minor variations.
6. Persist each path as a `paths` row plus an ordered set of `edges` referencing typed `nodes`.

## Architecture

```
  ┌──────────────────┐   wikilinks   ┌──────────────────┐
  │ MediaWiki API    │ ────────────▶ │ path_finder loop │
  └──────────────────┘               │                  │
                                     │  pick_next_hop ──┼──▶ Claude (Anthropic API)
                                     │  classify_type ──┼──▶ Claude
                                     │  summarize_theme─┼──▶ Claude
                                     │                  │
                                     │   upsert_node ───┼──▶ Supabase (nodes)
                                     │   insert_path  ──┼──▶ Supabase (paths + edges)
                                     └──────────────────┘
```

## Setup

See [`GITHUB_SETUP.md`](./GITHUB_SETUP.md) for getting the repo cloned and pushed for the first time. Once you've got the repo locally:

```bash
# 1. Python deps in a virtualenv (uses the 3.12 install, not system 3.9)
python3.12 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

# 2. Secrets
cp .env.example .env
# fill in ANTHROPIC_API_KEY and SUPABASE_SERVICE_ROLE_KEY
# (SUPABASE_URL is pre-filled with the Field Trips project URL)

# 3. Apply the Supabase schema
# Easiest: open https://supabase.com/dashboard/project/vjikcsifkvphuiwjrmqi/sql/new
# and paste supabase/migrations/0001_initial_schema.sql, then Run.
# Then: Project Settings → API → Exposed schemas → add "path_finder" → Save.

# 4. Sanity-check the script imports
python -m src.path_finder --help

# 5. Make a copy of the scenarios template
cp scenarios.example.yaml scenarios.yaml
```

## Running it

One scenario, ad-hoc:

```bash
python -m src.path_finder one --start "Monhegan" --end "Conservation movement" --permutations 3
```

Whole queue from YAML:

```bash
python -m src.path_finder run --scenarios scenarios.yaml
```

## Schema

All path-finder tables live in a dedicated `path_finder` Postgres schema in the Field Trips Supabase project — kept separate from `public` so we don't collide with the book-ingest tables already there. See [`supabase/migrations/0001_initial_schema.sql`](./supabase/migrations/0001_initial_schema.sql) for the full DDL.

- **`path_finder.nodes`** — every Wikipedia page touched. Typed (`place` / `idea` / `person` / `event` / `thing`). Optional `located_in` self-FK for grounding things to places (e.g. Monhegan Lighthouse `located_in` Monhegan Island). Optional `coordinates` for physical places.
- **`path_finder.paths`** — one row per rabbit-hole session. Has `start_node_id`, `end_node_id`, `total_hops`, `theme`, `completed`, `permutation_group`.
- **`path_finder.edges`** — one row per hop. Path-scoped, so the same `(from, to)` can appear in many paths. The `path_finder.connections` view dedupes globally.

Useful queries (paste into the Supabase SQL editor as-is):

```sql
-- All things on Monhegan
SELECT * FROM path_finder.nodes WHERE is_monhegan_object;

-- All ideas reachable from any Monhegan object
SELECT DISTINCT n.*
FROM path_finder.nodes n
JOIN path_finder.edges e ON e.to_node_id = n.id
JOIN path_finder.paths p ON p.id = e.path_id
WHERE n.node_type = 'idea'
  AND p.start_node_id IN (SELECT id FROM path_finder.nodes WHERE is_monhegan_object);

-- All nodes in a single path, in order (start through end)
SELECT n.title, edge_pos AS position
FROM (
  SELECT from_node_id AS node_id, position_in_path AS edge_pos
    FROM path_finder.edges WHERE path_id = <some_path_id>
  UNION ALL
  SELECT to_node_id AS node_id, position_in_path + 1 AS edge_pos
    FROM path_finder.edges WHERE path_id = <some_path_id>
      AND position_in_path = (SELECT MAX(position_in_path) FROM path_finder.edges WHERE path_id = <some_path_id>)
) hops
JOIN path_finder.nodes n ON n.id = hops.node_id
ORDER BY edge_pos;
```

The Python client is configured (via `ClientOptions(schema="path_finder")`) so that calls like `sb.table("nodes")` automatically resolve to `path_finder.nodes` — you don't need to qualify in code, only in raw SQL.

## Building it out (Claude Code TODOs)

The skeleton is in [`src/path_finder.py`](./src/path_finder.py). Search for `TODO(vibe-code)` — those are the bodies to fill in. Specifically:

1. **`pick_next_hop`** — shortlist candidates before sending to Claude (Wikipedia pages can have 500+ links; we don't need them all). Skip dates, "List of ..." pages, and overly generic terms. Add retry-on-invalid-response.
2. **`upsert_node`** — implement the SELECT-then-INSERT pattern. Classify type only on new nodes. Handle concurrent insert races.
3. **`insert_path`** — wrap path + edges in a Supabase transaction. Derive edges from consecutive pairs in `hops`.
4. **Monhegan object seed pass** — small script or notebook to populate the anchor `nodes`: lighthouse, art colony, tick eradication program, Manana Island, etc. Set `is_monhegan_object = true` and `located_in` → Monhegan Island. Run before the first `scenarios.yaml` so paths starting from those nodes find them already in the DB.

## Future

- Coordinates on physical-place nodes for Jeremy's map view.
- A small read API or Supabase view for the website to consume.
- A scheduled job that runs new scenarios from a queue table.
- Eventually: news article → entity extraction → auto-generated start/end pairs.

## Layout

```
path-finder/
├── README.md
├── GITHUB_SETUP.md            <- first-time setup walkthrough
├── .env.example
├── .gitignore
├── requirements.txt
├── scenarios.example.yaml     <- copy to scenarios.yaml and edit
├── supabase/
│   └── migrations/
│       └── 0001_initial_schema.sql
└── src/
    ├── __init__.py
    └── path_finder.py         <- the whole skeleton lives here for now
```
