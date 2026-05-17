---
name: path-finder
description: >
  Field Trips path-finder widget. Bulk-runs Wikipedia paths and manages anchors. Use when Sarah or Jeremy wants to find paths, add anchors, list anchors, "connect X to Y", "build paths for Monhegan", etc.
---

# Path-finder widget

Minimum round trips. Bundle questions. Show output. No analysis.

## Step 1 — Preflight (single bash call)

Always start by fetching places AND anchors in parallel so the form can be filled in ONE shot:

```bash
cd $HOME/field-trips/path-finder
echo "PLACES:"
.venv/bin/python -m src.path_finder places --json
echo "ANCHORS:"
.venv/bin/python -m src.path_finder anchor list --json
```

Parse both JSON blobs.

## Step 2 — ONE big form (single AskUserQuestion with 4 questions)

Call AskUserQuestion with all four questions at once. The user fills them all in before submitting.

Question 1:
- question: "What do you want to do?"
- header: "Action"
- options:
  - label: "Find paths"
    description: "Run paths from anchor → concept"
  - label: "Add anchors"
    description: "Pin new anchors to a place (skip Anchor + Concepts below)"
  - label: "List anchors"
    description: "Just show what's saved (skip the rest)"

Question 2:
- question: "Anchor (skip if just listing)"
- header: "Anchor"
- options: (one per existing anchor) `label: "<title>"` `description: "<node_type> · on <place_title>"`, then `label: "+ New anchor"` `description: "I'll add one — type Wikipedia URLs in Concepts below"`

Question 3:
- question: "Concepts — one Wikipedia title or URL per line. Up to 5 per batch. (For Find paths: destinations. For Add anchors: the anchor URLs.)"
- header: "Concepts / URLs"
- options:
  - label: "(typed below)"
    description: "Use Other and paste one per line — e.g. Marxism, Conservation movement"
  - label: "(skip)"
    description: "Only for List anchors"

Question 4:
- question: "Paths per concept (only used for Find paths)"
- header: "Paths"
- options:
  - label: "1"
    description: "Quick"
  - label: "3"
    description: "Thorough"

## Step 3 — Run (single bash call)

Based on Q1:

### Find paths
If anchor is an existing one, use its `wikipedia_url` from preflight JSON. Place is inferred from that anchor's `place_wikipedia_url`. Then run all concepts in parallel:

```bash
cd $HOME/field-trips/path-finder
mkdir -p /tmp/pf-logs && rm -f /tmp/pf-logs/*.log
PLACE="<place_wikipedia_url>"
ANCHOR="<anchor_wikipedia_url>"
PERMS=<1 or 3>
while IFS= read -r CONCEPT; do
  [ -z "$CONCEPT" ] && continue
  SAFE=$(echo "$CONCEPT" | tr ' /:' '___')
  .venv/bin/python -m src.path_finder one --place "$PLACE" --anchor "$ANCHOR" --concept "$CONCEPT" --permutations "$PERMS" > "/tmp/pf-logs/$SAFE.log" 2>&1 &
done <<EOF
<concept 1>
<concept 2>
EOF
wait
for log in /tmp/pf-logs/*.log; do
  CONCEPT=$(basename "$log" .log | tr '_' ' ')
  echo ""
  echo "─── $CONCEPT ──────────"
  cat "$log"
done
```

### Add anchors
If the user picked "+ New anchor" or chose "Add anchors" as action, the URLs in Q3 are anchor URLs (not concepts). Default place is the first existing place (or ask in a follow-up if there are 0 or 2+).

```bash
cd $HOME/field-trips/path-finder
PLACE="<place_wikipedia_url>"
while IFS= read -r ANCHOR; do
  [ -z "$ANCHOR" ] && continue
  .venv/bin/python -m src.path_finder anchor add --place "$PLACE" --anchor "$ANCHOR"
done <<EOF
<anchor 1>
<anchor 2>
EOF
```

### List anchors
```bash
cd $HOME/field-trips/path-finder && .venv/bin/python -m src.path_finder anchor list
```

## Rules

- Maximum 3 round trips total: preflight, form, run.
- Bundle all questions in ONE AskUserQuestion call.
- Never analyse the output. Print it verbatim.
- If user is missing info (e.g. picked "+ New anchor" and didn't enter URLs), ask ONE follow-up — never a string of questions.
