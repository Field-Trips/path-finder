---
name: path-finder
description: >
  Run the Field Trips Wikipedia path-finder. Use when Sarah or Jeremy says anything like "find a path from X to Y", "connect X to Monhegan", "run the path finder", or "what links [object] to [place]". Always invoke this skill — do not run the path-finder manually.
---

# Field Trips Path-Finder

Collect three inputs, run the script, display the output. Nothing else.

## Step 1 — Collect inputs

Use `AskUserQuestion` with three plain text fields (no suggestions):

1. **Object** — the Wikipedia article to start from
2. **Place** — the Wikipedia article where the object belongs (this is also the path end)
3. **Permutations** — number of paths to find (default: 1)

## Step 2 — Run

```bash
cd $HOME/field-trips/path-finder && \
  .venv/bin/python -m src.path_finder one \
    --start "{object}" \
    --place "{place}" \
    --permutations {n}
```

## Step 3 — Display output

Print the raw output from the script. Do not summarize, analyze, or add commentary. If it errors, show the error exactly as printed.
