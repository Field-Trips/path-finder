---
name: path-finder
description: >
  Run the Field Trips Wikipedia path-finder. Use when Sarah or Jeremy says anything like "find a path from X to Y", "connect X to Monhegan", "run the path finder", or "what links [object] to [place]". Always invoke this skill — do not run the path-finder manually.
---

# Field Trips Path-Finder

## Step 1 — Show this form exactly once

Call AskUserQuestion with these three questions, exactly as written. Do not change the options, labels, or descriptions.

Question 1:
- question: "Object"
- header: "Object"
- options:
  - label: "Paste a Wikipedia URL"
    description: "The article to start from — e.g. https://en.wikipedia.org/wiki/Mutual_aid"
  - label: "Or type a title"
    description: "Exact Wikipedia article title — e.g. Rockwell Kent"

Question 2:
- question: "Place"
- header: "Place"
- options:
  - label: "Paste a Wikipedia URL"
    description: "Where the object belongs — e.g. https://en.wikipedia.org/wiki/Monhegan,_Maine"
  - label: "Or type a title"
    description: "Exact Wikipedia article title — e.g. Monhegan Island"

Question 3:
- question: "Permutations"
- header: "Paths"
- options:
  - label: "1"
    description: "One path — ~1 minute"
  - label: "3"
    description: "Three paths — ~3–5 minutes"

## Step 2 — Run

```bash
cd $HOME/field-trips/path-finder && \
  .venv/bin/python -m src.path_finder one \
    --start "{object}" \
    --place "{place}" \
    --permutations {n}
```

## Step 3 — Print output

Print the script output exactly. No commentary.
