---
name: path-finder
description: >
  Run the Field Trips Wikipedia path-finder to discover and persist paths connecting an object to the place it belongs to. Use this skill whenever Sarah or Jeremy wants to connect an object to a place through Wikipedia links, grow the path_finder database, or says anything like "find a path from X to Y", "connect X to Monhegan", "run the path finder", "add paths to the database", or "what links [object] to [place]". Always invoke this skill — do not attempt to run the path-finder manually without it.
---

# Field Trips Path-Finder

This skill runs the Wikipedia path-finder: given an object and the place it belongs to, it walks the Wikipedia link graph from object → place one hop at a time (Claude picks each next hop), then persists every node, path, and edge to the Field Trips Supabase database.

Every path in Field Trips connects an object to its place (e.g. Lobster → Monhegan Island, Marxism → Monhegan Island, Weaving → Bauhaus).

**Project location:** `$HOME/field-trips/path-finder`
**Supabase project:** `vjikcsifkvphuiwjrmqi` (schema: `path_finder`)

---

## Step 1: Collect inputs

Use `AskUserQuestion` to ask for all three inputs at once before doing anything else. Ask:

1. **Object** — the Wikipedia article to start from (the thing, idea, person, or concept being curated — e.g. "Lobster", "Marxism", "Rockwell Kent", "Weaving")
2. **Place** — the Wikipedia article for where the object belongs (the destination — e.g. "Monhegan Island", "Maine", "Bauhaus", "New York City")
3. **Permutations** — how many distinct paths to find (default: 1; more = more diverse routes = richer database, but takes longer)

Offer permutation options: 1 (quick), 3 (standard), 5 (thorough).

## Step 2: Run the path-finder

```bash
cd $HOME/field-trips/path-finder && \
  .venv/bin/python -m src.path_finder one \
    --start "{object}" \
    --place "{place}" \
    --permutations {n}
```

Replace `{object}`, `{place}`, `{n}` with the user's answers. Quote titles so multi-word names work correctly.

The script will:
- Walk the Wikipedia link graph from object → place
- Ask Claude to pick each next hop toward the place
- Classify each page as place / idea / person / event / thing
- Tag the object node with its place (located_in FK)
- Persist nodes, path, and edges to Supabase

This takes 30–120 seconds per permutation depending on path length.

## Step 3: Report results

After the command finishes, present the output cleanly:

- Show each path as: `Object → Hop 1 → Hop 2 → … → Place`
- Note the theme label Claude generated (e.g. "via ecological restoration")
- Note whether each path completed (✓) or hit the hop cap (×)
- Mention that nodes, paths, and edges are now in Supabase

If the command errors, show the error and suggest common fixes:
- **Wikipedia page not found** → check for typos; try the exact article title as it appears on Wikipedia
- **hop cap hit without reaching place** → try increasing `--max-hops` (default 10) or picking a more connected place article
- **Supabase error** → check that `.env` has valid `SUPABASE_SERVICE_ROLE_KEY`
