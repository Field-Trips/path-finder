---
name: path-finder
description: >
  Field Trips path-finder widget. Bulk-runs Wikipedia paths and manages anchors. Use when Sarah or Jeremy wants to find paths, add anchors, list anchors, "connect X to Y", "build paths for Monhegan", etc.
---

# Path-finder widget

Minimum round trips. Bundle questions. Show output. No analysis.

## Step 1 — Preflight (single bash call)

```bash
cd $HOME/field-trips/path-finder
echo "PLACES:"
.venv/bin/python -m src.path_finder places --json
echo "ANCHORS:"
.venv/bin/python -m src.path_finder anchor list --json
```

Parse both JSON blobs.

## Step 2 — Bundled form (ONE AskUserQuestion with 4 questions)

The user fills in ALL questions before submitting. The free-text fields are entered via the "Other" option on each question.

Question 1:
- question: "What do you want to do?"
- header: "Action"
- options:
  - label: "Find paths"
    description: "Anchor → concept paths"
  - label: "Add anchors"
    description: "Pin new anchors to a place"
  - label: "List anchors"
    description: "Just show what's saved"

Question 2:
- question: "Anchor (for Find paths)"
- header: "Anchor"
- options: (one per existing anchor) `label: "<title>"` `description: "<node_type> · on <place_title>"`, then `label: "+ New anchor"` `description: "Type its Wikipedia URL in Other"`

Question 3:
- question: "Click 'Other' below and paste one Wikipedia title/URL per line (concepts if finding paths, anchor URLs if adding). Up to 5."
- header: "URLs"
- options:
  - label: "I'll paste in Other below"
    description: "One per line"
  - label: "Just list anchors"
    description: "No URLs needed for the List action"

Question 4:
- question: "How many paths per concept? (Find paths only)"
- header: "Paths"
- options:
  - label: "1"
    description: "Quick"
  - label: "3"
    description: "Thorough"

## Step 3 — Run (single bash call)

Branch on Q1:

### Find paths
Anchor URL: use the picked anchor's `wikipedia_url` from preflight. Place URL: use that anchor's `place_wikipedia_url`.

```bash
cd $HOME/field-trips/path-finder
mkdir -p /tmp/pf-logs && rm -f /tmp/pf-logs/*.log
PLACE="<place_url>"
ANCHOR="<anchor_url>"
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
URLs in Q3 are anchor URLs. Use the first place from preflight (or ask one follow-up if there are 0/multiple).

```bash
cd $HOME/field-trips/path-finder
PLACE="<place_url>"
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

- Max 3 round trips: preflight, form, run.
- Bundle all 4 questions in ONE AskUserQuestion call.
- Never analyse the output — print verbatim.
- If a follow-up is unavoidable (e.g. user picked "+ New anchor" but didn't enter URLs), ask only ONE more question.
