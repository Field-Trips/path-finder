---
name: path-finder
description: >
  Field Trips path-finder widget. Wrapper around the local Python script. Use when Sarah or Jeremy wants to find paths, add anchors, or list anchors. Optimised for BULK operations — runs many concepts in parallel. Use for "find paths", "add anchor", "list anchors", "connect X to Y", "build paths for Monhegan", etc.
---

# Path-finder widget

You are a thin wrapper. Run bash. Show output. Do not analyse or summarise.

## Step 1 — Main menu

Call AskUserQuestion:
- question: "What would you like to do?"
- header: "Action"
- options:
  - label: "Find paths (bulk)"
    description: "Pick a place + anchor, run many concepts in parallel"
  - label: "Add anchors"
    description: "Pin one or more Wikipedia articles as anchors on a place"
  - label: "List anchors"
    description: "Show all saved anchors"

Branch on the answer.

---

## Branch A — Find paths (bulk)

### A1. Pick a place

Run:
```bash
cd $HOME/field-trips/path-finder && .venv/bin/python -m src.path_finder places --json
```

Parse the JSON. Call AskUserQuestion with one option per place (label = title, description = "use this place"), plus one option `label: "+ Add new place"` `description: "Type a Wikipedia URL"`.

If the user picks "+ Add new place": call AskUserQuestion with one question for the URL (options: `Paste a Wikipedia URL` / `Or type a title`). Treat the typed answer as the place URL/title. There is no anchor yet on this place so skip to A2 in "new anchor" mode (the user will define an anchor below; you'll pass --place X --anchor Y).

Otherwise, use the picked place's `wikipedia_url` as PLACE.

### A2. Pick an anchor

Run:
```bash
cd $HOME/field-trips/path-finder && .venv/bin/python -m src.path_finder anchor list --place "PLACE" --json
```

Parse the JSON. Call AskUserQuestion with one option per anchor (label = title, description = node_type), plus `+ Add new anchor`.

If "+ Add new anchor": call AskUserQuestion for the anchor's Wikipedia URL/title (same two-option pattern). Then run:
```bash
cd $HOME/field-trips/path-finder && .venv/bin/python -m src.path_finder anchor add --place "PLACE" --anchor "ANCHOR_URL"
```
Use the new anchor's URL as ANCHOR.

Otherwise, use the picked anchor's `wikipedia_url` as ANCHOR.

### A3. Concepts (bulk input)

Call AskUserQuestion:
- question: "Concepts — one Wikipedia title or URL per line. Cap at 5 per batch to stay under rate limits."
- header: "Concepts"
- options:
  - label: "Enter concepts"
    description: "One per line — e.g. Marxism, Conservation movement, American Scene painting"
  - label: "Paste Wikipedia URLs"
    description: "One URL per line"

The user will type the concepts via "Other". Split on newlines, strip blanks. If they typed more than 5, tell them to pick 5 max and ask again.

### A4. Permutations

Call AskUserQuestion:
- question: "How many paths per concept?"
- header: "Permutations"
- options:
  - label: "1"
    description: "Quick — one path each"
  - label: "3"
    description: "Three distinct paths each"

### A5. Run in parallel

Build one bash command that runs every concept in parallel, each writing to its own log file. Use a single Bash call:

```bash
cd $HOME/field-trips/path-finder
mkdir -p /tmp/pf-logs && rm -f /tmp/pf-logs/*.log
PLACE="<PLACE_URL>"
ANCHOR="<ANCHOR_URL>"
PERMS=<1 or 3>

# Loop through concepts (one per line in a variable):
while IFS= read -r CONCEPT; do
  [ -z "$CONCEPT" ] && continue
  SAFE=$(echo "$CONCEPT" | tr ' /:' '___')
  .venv/bin/python -m src.path_finder one \
    --place   "$PLACE" \
    --anchor  "$ANCHOR" \
    --concept "$CONCEPT" \
    --permutations "$PERMS" > "/tmp/pf-logs/$SAFE.log" 2>&1 &
done <<EOF
<concept 1>
<concept 2>
<concept 3>
EOF

wait

# Print results
for log in /tmp/pf-logs/*.log; do
  CONCEPT=$(basename "$log" .log | tr '_' ' ')
  echo ""
  echo "─── $CONCEPT ──────────────────────────────────────"
  cat "$log"
done
```

Print the combined output verbatim. No commentary.

---

## Branch B — Add anchors

### B1. Pick a place
Same as A1.

### B2. Anchors to add

Call AskUserQuestion:
- question: "Anchors — one Wikipedia title or URL per line"
- header: "Anchors"
- options:
  - label: "Enter anchors"
    description: "One per line — e.g. Rockwell Kent, Lobster trap, Monhegan Light"
  - label: "Paste URLs"
    description: "One URL per line"

(Rationales are added later via terminal — bulk add is URLs only.)

### B3. Run

```bash
cd $HOME/field-trips/path-finder
PLACE="<PLACE_URL>"
while IFS= read -r ANCHOR; do
  [ -z "$ANCHOR" ] && continue
  .venv/bin/python -m src.path_finder anchor add \
    --place "$PLACE" \
    --anchor "$ANCHOR"
done <<EOF
<anchor 1>
<anchor 2>
EOF
```

Print output. No commentary.

---

## Branch C — List anchors

Run:
```bash
cd $HOME/field-trips/path-finder && .venv/bin/python -m src.path_finder anchor list
```

Print verbatim. No commentary.

---

## Rules

- Never analyse, summarise, or add narration. The Python script's output speaks for itself.
- If the user wants a single concept (not bulk), the same flow works with one line of input.
- Cap parallel concepts at 5 to stay under rate limits.
