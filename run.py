#!/usr/bin/env python3
"""
Field Trips path-finder — interactive runner.

Just run:  python3 run.py
"""

import subprocess
import sys
import os
import json

# ── colour helpers ──────────────────────────────────────────────────────────
def _c(code, text): return f"\033[{code}m{text}\033[0m"
bold   = lambda t: _c("1", t)
green  = lambda t: _c("32", t)
yellow = lambda t: _c("33", t)
red    = lambda t: _c("31", t)
dim    = lambda t: _c("2", t)
cyan   = lambda t: _c("36", t)

BANNER = f"""
{bold("╔══════════════════════════════════════════╗")}
{bold("║    Field Trips — Wikipedia Path-Finder   ║")}
{bold("╚══════════════════════════════════════════╝")}
"""

TIP = dim("""\
  Tip: you can enter either a plain title ("Monhegan Island") or
  paste a Wikipedia URL for precision when titles are ambiguous.
""")


SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))


def _venv_python() -> str:
    venv = os.path.join(SCRIPT_DIR, ".venv", "bin", "python")
    if not os.path.exists(venv):
        venv = os.path.join(SCRIPT_DIR, ".venv", "Scripts", "python.exe")
    if not os.path.exists(venv):
        print(red("\n  Error: virtual environment not found."))
        print("  Run:  python3 -m venv .venv && source .venv/bin/activate && pip install -r requirements.txt")
        sys.exit(1)
    return venv


def ask(prompt: str, default: str = "") -> str:
    hint = f" [{default}]" if default else ""
    try:
        val = input(f"  {bold('→')} {prompt}{hint}: ").strip()
    except (KeyboardInterrupt, EOFError):
        print("\n\nCancelled.")
        sys.exit(0)
    return val if val else default


def ask_int(prompt: str, default: int, lo: int, hi: int) -> int:
    while True:
        raw = ask(prompt, str(default))
        try:
            n = int(raw)
            if lo <= n <= hi:
                return n
        except ValueError:
            pass
        print(f"     {yellow('Please enter a number between')} {lo} {yellow('and')} {hi}.")


def resolve_article(label: str) -> tuple[str, str]:
    """Interactively prompt for a Wikipedia title/URL, validate, return (title, url)."""
    while True:
        raw = ask(f"{label} — Wikipedia title or URL")
        if not raw:
            print(f"     {yellow('Required.')}")
            continue

        print(f"     {dim('Checking Wikipedia...')}", end="\r")
        result = subprocess.run(
            [_venv_python(), "-c", f"""
import sys, json
sys.path.insert(0, '.')
from dotenv import load_dotenv; load_dotenv(override=True)
from src.path_finder import fetch_wiki_page, DisambiguationError
try:
    p = fetch_wiki_page({raw!r})
    intro = (p.intro_text or '').split('. ')[0][:200]
    print(json.dumps({{"ok": True, "title": p.title, "url": p.url, "intro": intro}}))
except DisambiguationError as e:
    print(json.dumps({{"ok": False, "disambiguation": True, "options": e.options, "msg": str(e)}}))
except ValueError as e:
    print(json.dumps({{"ok": False, "disambiguation": False, "msg": str(e)}}))
"""],
            cwd=SCRIPT_DIR,
            capture_output=True, text=True,
        )
        print("                                    ", end="\r")

        try:
            data = json.loads(result.stdout.strip().splitlines()[-1])
        except Exception:
            print(f"     {red('Unexpected error:')} {result.stderr[:200]}")
            continue

        if data.get("ok"):
            print(f"     {green('✓')} {bold(data['title'])}")
            if data.get("intro"):
                print(f"     {dim(data['intro'] + '...')}")
            print()
            return data["title"], data["url"]

        if data.get("disambiguation"):
            print(f"     {yellow('Disambiguation page')} — that title matches multiple articles:")
            for opt in (data.get("options") or [])[:8]:
                print(f"       {dim('•')} {opt}")
            print(f"     {dim('Go to Wikipedia, find the exact article, and paste the URL.')}\n")
            continue

        print(f"     {red('Not found:')} {data.get('msg', 'unknown error')}\n")


# ── Supabase queries (used by pickers) ──────────────────────────────────────

def _query_json(args: list[str]) -> list:
    """Run a path_finder CLI command that supports --json and return parsed JSON."""
    result = subprocess.run(
        [_venv_python(), "-m", "src.path_finder", *args, "--json"],
        cwd=SCRIPT_DIR, capture_output=True, text=True,
    )
    try:
        return json.loads(result.stdout.strip().splitlines()[-1])
    except Exception:
        return []


def fetch_places() -> list[dict]:
    return _query_json(["places"])


def fetch_anchors(place_url: str = "") -> list[dict]:
    args = ["anchor", "list"]
    if place_url:
        args += ["--place", place_url]
    return _query_json(args)


# ── Pickers ─────────────────────────────────────────────────────────────────

def pick_place() -> tuple[str, str]:
    """Show existing places; user picks one or adds new. Returns (title, url)."""
    places = fetch_places()
    if not places:
        print(f"  {dim('No places saved yet — adding a new one.')}")
        return resolve_article("Place — Wikipedia title or URL (the map this anchor lives on, e.g. 'Monhegan Island')")

    print(f"\n  {bold('Pick a place:')}")
    for i, p in enumerate(places, 1):
        print(f"    {cyan(str(i))}  {p['title']}")
    print(f"    {cyan('n')}  + Add new place")

    while True:
        choice = ask("Choice", "1").lower()
        if choice == "n":
            return resolve_article("Place — Wikipedia title or URL")
        try:
            idx = int(choice) - 1
            if 0 <= idx < len(places):
                p = places[idx]
                print(f"     {green('✓')} {bold(p['title'])}\n")
                return p["title"], p["wikipedia_url"]
        except ValueError:
            pass
        print(f"     {yellow('Please pick a number or n.')}")


def pick_anchor(place_url: str = "", place_title: str = "", exclude_url: str = "", prompt_label: str = "Pick an anchor") -> dict:
    """Show existing anchors (optionally filtered to a place); user picks one or adds new.
    Returns full anchor record.

    `exclude_url` lets the caller hide a specific anchor (e.g. the primary anchor
    when picking a branch anchor)."""
    anchors = fetch_anchors(place_url)
    if exclude_url:
        anchors = [a for a in anchors if a.get("wikipedia_url") != exclude_url]
    label = f" on {bold(place_title)}" if place_title else ""
    where = f" on {place_title}" if place_title else ""

    if not anchors:
        print(f"  {dim('No' + (' other' if exclude_url else '') + ' anchors saved yet' + where + ' — adding a new one.')}")
        return inline_add_anchor(prefilled_place_url=place_url, prefilled_place_title=place_title)

    print(f"\n  {bold(prompt_label + label + ':')}")
    for i, a in enumerate(anchors, 1):
        node_type = a.get("node_type") or "?"
        place_suffix = "" if place_url else f" · on {a.get('place_title') or '?'}"
        print(f"    {cyan(str(i))}  {a['title']}  {dim(f'({node_type}{place_suffix})')}")
    print(f"    {cyan('n')}  + Add new anchor")

    while True:
        choice = ask("Choice", "1").lower()
        if choice == "n":
            return inline_add_anchor(prefilled_place_url=place_url, prefilled_place_title=place_title)
        try:
            idx = int(choice) - 1
            if 0 <= idx < len(anchors):
                a = anchors[idx]
                print(f"     {green('✓')} {bold(a['title'])} on {bold(a.get('place_title') or '?')}\n")
                return a
        except ValueError:
            pass
        print(f"     {yellow('Please pick a number or n.')}")


def inline_add_anchor(prefilled_place_url: str = "", prefilled_place_title: str = "") -> dict:
    """Add a new anchor and return its record so it can flow into the next step."""
    print(f"\n  {bold('Add a new anchor')}")
    print(f"  {dim('An anchor is a person/place/thing pinned on the map of a place.')}\n")

    if prefilled_place_url:
        place_title, place_url = prefilled_place_title, prefilled_place_url
        print(f"  {dim('Place:')} {bold(place_title)}\n")
    else:
        place_title, place_url = pick_place()

    # Sanity check: show existing anchors on this place so the user doesn't
    # accidentally re-add one or forget what's there.
    existing = fetch_anchors(place_url)
    if existing:
        print(f"  {dim('Existing anchors on')} {bold(place_title)}{dim(':')}")
        for a in existing:
            node_type = a.get("node_type") or "?"
            print(f"    {dim('·')} {a.get('title')}  {dim('(' + node_type + ')')}")
        print()

    anchor_title, anchor_url = resolve_article(
        "Anchor — Wikipedia title or URL (the person/place/thing being pinned, e.g. 'Lobster trap', 'Rockwell Kent')"
    )

    print(f"  {dim('Rationale (optional) — why this anchor belongs to this place. Press Enter to skip.')}")
    rationale = ask("Rationale", "")
    print(f"  {dim('Custom image URL (optional) — overrides Wikipedia image. Press Enter to skip.')}")
    image = ask("Image URL", "")

    cmd = [_venv_python(), "-m", "src.path_finder", "anchor", "add",
           "--place", place_url, "--anchor", anchor_url]
    if rationale:
        cmd += ["--rationale", rationale]
    if image:
        cmd += ["--image", image]

    print()
    result = subprocess.run(cmd, cwd=SCRIPT_DIR)
    print()

    if result.returncode != 0:
        print(f"  {red('Failed to add anchor.')}")
        return {}

    # Re-fetch the saved row so callers get fresh data
    for a in fetch_anchors(place_url):
        if a["wikipedia_url"] == anchor_url:
            return a
    return {
        "title": anchor_title, "wikipedia_url": anchor_url,
        "place_title": place_title, "place_wikipedia_url": place_url,
    }


# ── actions ─────────────────────────────────────────────────────────────────

def action_add_anchor():
    inline_add_anchor()


def action_list_anchors():
    print(f"\n  {bold('Anchors')}\n")
    cmd = [_venv_python(), "-m", "src.path_finder", "anchor", "list"]
    subprocess.run(cmd, cwd=SCRIPT_DIR)
    print()


def ask_concepts() -> list[tuple[str, str]]:
    """Collect 1-5 concepts as a comma-separated list. Each is validated against Wikipedia.
    Tip: paste URLs to avoid commas-in-titles issues. Returns list of (title, url) tuples."""
    print(f"\n  {bold('Concepts')}")
    print(f"  {dim('Comma-separated. Max 5. Paste Wikipedia URLs for precision.')}")
    print(f"  {dim('Example: https://en.wikipedia.org/wiki/Marxism, https://en.wikipedia.org/wiki/Anthroposophy')}\n")

    raw = ask("Concepts", "")
    if not raw:
        return []
    items = [c.strip() for c in raw.split(",") if c.strip()]
    if len(items) > 5:
        print(f"  {yellow('More than 5 concepts — capping at 5 to stay under rate limits.')}")
        items = items[:5]

    out: list[tuple[str, str]] = []
    for i, item in enumerate(items, 1):
        print(f"\n  {dim(f'[{i}/{len(items)}]')} {item}")
        title, url = _validate_wikipedia(item)
        if title:
            out.append((title, url))
    print()
    return out


def _validate_wikipedia(raw: str) -> tuple[str, str]:
    """Validate a Wikipedia title/URL, returning (title, url) or ('', '') if invalid."""
    print(f"     {dim('Checking Wikipedia...')}", end="\r")
    result = subprocess.run(
        [_venv_python(), "-c", f"""
import sys, json
sys.path.insert(0, '.')
from dotenv import load_dotenv; load_dotenv(override=True)
from src.path_finder import fetch_wiki_page, DisambiguationError
try:
    p = fetch_wiki_page({raw!r})
    print(json.dumps({{"ok": True, "title": p.title, "url": p.url}}))
except DisambiguationError as e:
    print(json.dumps({{"ok": False, "disambiguation": True, "options": e.options[:8]}}))
except ValueError as e:
    print(json.dumps({{"ok": False, "msg": str(e)}}))
"""], cwd=SCRIPT_DIR, capture_output=True, text=True,
    )
    print("                                    ", end="\r")
    try:
        data = json.loads(result.stdout.strip().splitlines()[-1])
    except Exception:
        print(f"     {red('Unexpected error.')}")
        return "", ""
    if data.get("ok"):
        print(f"     {green('✓')} {bold(data['title'])}")
        return data["title"], data["url"]
    if data.get("disambiguation"):
        print(f"     {yellow('Disambiguation')} — pick from:")
        for opt in data.get("options", []):
            print(f"       {dim('•')} {opt}")
    else:
        print(f"     {red('Not found:')} {data.get('msg', 'unknown')}")
    return "", ""


def pick_place_or_all() -> tuple[str, str]:
    """Like pick_place but also offers 'All places'. Returns ('', '') for all."""
    places = fetch_places()
    if not places:
        return "", ""
    print(f"\n  {bold('Filter by place:')}")
    print(f"    {cyan('a')}  All places")
    for i, p in enumerate(places, 1):
        print(f"    {cyan(str(i))}  {p['title']}")
    while True:
        choice = ask("Choice", "a").lower()
        if choice == "a":
            return "", ""
        try:
            idx = int(choice) - 1
            if 0 <= idx < len(places):
                p = places[idx]
                return p["title"], p["wikipedia_url"]
        except ValueError:
            pass
        print(f"     {yellow('Please pick a number or a.')}")


def action_find_paths():
    print(f"\n  {bold('Create new path')}")
    print(f"  {dim('Place → Anchor → Concept. Pick or create each in order.')}\n")

    # Step 1: place
    place_title, place_url = pick_place()

    # Step 2: anchor (filtered to this place)
    anchor = pick_anchor(place_url=place_url, place_title=place_title)
    if not anchor:
        return
    anchor_title = anchor["title"]
    anchor_url   = anchor["wikipedia_url"]

    # Step 3: concepts (comma-separated)
    concepts = ask_concepts()
    if not concepts:
        print("  Cancelled.\n")
        return

    print(f"  {bold('How many distinct paths?')}  {dim('1 = quick · 3 = standard · 5 = thorough')}")
    perms = ask_int("Permutations", default=1, lo=1, hi=10)
    print()

    print(f"  {bold('Ready to run:')}")
    print(f"    Place      {green(place_title)}")
    print(f"    Anchor     {green(anchor_title)}")
    for i, (t, _) in enumerate(concepts, 1):
        label = "Concepts" if i == 1 else "        "
        print(f"    {label}   {green(t)}")
    print(f"    Paths each {green(str(perms))}")
    print(f"\n  {dim('Each path takes ~1–3 minutes. Concepts run in parallel.')}\n")

    try:
        go = input(f"  {bold('→')} Go? [Y/n]: ").strip().lower()
    except (KeyboardInterrupt, EOFError):
        print("\n\nCancelled.")
        return
    if go not in ("", "y", "yes"):
        print("  Cancelled.\n")
        return

    if len(concepts) == 1:
        cmd = [_venv_python(), "-m", "src.path_finder", "one",
               "--place", place_url,
               "--anchor", anchor_url,
               "--concept", concepts[0][1],
               "--permutations", str(perms)]
    else:
        cmd = [_venv_python(), "-m", "src.path_finder", "batch",
               "--place", place_url,
               "--anchor", anchor_url,
               "--concepts", ",".join(t for _, t in [(c[0], c[1]) for c in concepts]),
               "--permutations", str(perms)]

    print(f"\n  {dim('Running … (Ctrl+C to stop)')}\n")
    print("  " + "─" * 50)
    result = subprocess.run(cmd, cwd=SCRIPT_DIR)
    print("  " + "─" * 50)
    if result.returncode == 0:
        print(f"\n  {green('Done.')} Paths saved to the Field Trips database.\n")
    else:
        print(f"\n  {red('Something went wrong')} — see the error above.\n")

    # Retry-failed flow: check for concepts that didn't complete on this anchor
    offer_retry_failed(anchor_url, concepts, perms)


def action_create_indirect_path():
    """Place → Anchor → Branch Anchor → Concept, deliberately constructed."""
    print(f"\n  {bold('Create new indirect path')}")
    print(f"  {dim('Place → Anchor → Branch Anchor → Concept. The path passes through TWO anchors on the same place.')}\n")

    # Step 1: place
    place_title, place_url = pick_place()

    # Step 2: primary anchor (the one the visitor first picks up on the map)
    print(f"\n  {dim('First, the primary anchor — the object visitors first encounter on the map.')}")
    primary = pick_anchor(place_url=place_url, place_title=place_title, prompt_label="Pick the primary anchor")
    if not primary:
        return
    primary_title = primary["title"]
    primary_url   = primary["wikipedia_url"]

    # Step 3: branch anchor (the bridge object the path travels through)
    print(f"\n  {dim('Next, the branch anchor — the second object the path travels through on its way to the concept.')}")
    branch = pick_anchor(
        place_url=place_url,
        place_title=place_title,
        exclude_url=primary_url,
        prompt_label="Pick the branch anchor",
    )
    if not branch:
        return
    branch_title = branch["title"]
    branch_url   = branch["wikipedia_url"]

    # Step 4: concepts
    concepts = ask_concepts()
    if not concepts:
        print("  Cancelled.\n")
        return

    print(f"  {bold('How many distinct paths per concept?')}  {dim('1 = quick · 3 = standard')}")
    perms = ask_int("Permutations", default=1, lo=1, hi=5)
    print()

    print(f"  {bold('Ready to run:')}")
    print(f"    Place             {green(place_title)}")
    print(f"    Primary anchor    {green(primary_title)}")
    print(f"    Branch anchor     {green(branch_title)}")
    for i, (t, _) in enumerate(concepts, 1):
        label = "Concepts" if i == 1 else "        "
        print(f"    {label}          {green(t)}")
    print(f"    Paths each        {green(str(perms))}")
    print(f"\n  {dim('Path will travel: ' + place_title + ' → ' + primary_title + ' → ' + branch_title + ' → [concept]')}")
    print(f"  {dim('Each path takes ~2-4 minutes (three stages instead of two).')}\n")

    try:
        go = input(f"  {bold('→')} Go? [Y/n]: ").strip().lower()
    except (KeyboardInterrupt, EOFError):
        print("\n\nCancelled.")
        return
    if go not in ("", "y", "yes"):
        print("  Cancelled.\n")
        return

    print(f"\n  {dim('Running … (Ctrl+C to stop)')}\n")
    print("  " + "─" * 50)
    for title, url in concepts:
        print(f"\n  {dim('Concept:')} {bold(title)}")
        cmd = [_venv_python(), "-m", "src.path_finder", "branched",
               "--place",         place_url,
               "--anchor",        primary_url,
               "--branch-anchor", branch_url,
               "--concept",       url,
               "--permutations",  str(perms)]
        subprocess.run(cmd, cwd=SCRIPT_DIR)
    print("  " + "─" * 50)
    print(f"\n  {green('Done.')}\n")


def offer_retry_failed(anchor_url: str, concepts: list[tuple[str, str]], perms: int) -> None:
    """Loop: keep listing concepts with zero completed paths and let the user
    retry with a higher cap. With the new architecture, incomplete paths are
    never saved to the DB — so 'failed' simply means 'no completed path yet'.
    Continues until the user skips or every concept has at least one
    completed path."""
    current_pool: list[tuple[str, str]] = list(concepts)
    last_cap = 15  # default stage-2 cap; ratchets up on each loop

    while True:
        failed: list[tuple[str, str]] = []
        for title, url in current_pool:
            if _concept_completed_count(anchor_url, url) == 0:
                failed.append((title, url))

        if not failed:
            return

        print(f"\n  {yellow('▲ Some concepts have no completed path yet:')}")
        for i, (t, _) in enumerate(failed, 1):
            print(f"    {cyan(str(i))}  {t}")
        print(f"    {cyan('a')}  Retry all with more hops")
        print(f"    {cyan('b')}  Find a branch through another anchor")
        print(f"    {cyan('n')}  Skip retry")

        choice = ask("Choice", "n").lower()
        if choice in ("n", "no", ""):
            return

        if choice == "b":
            # Branch sub-flow: pick which failed concept to branch, then which anchor to branch through
            if len(failed) == 1:
                target = failed[0]
            else:
                print(f"\n  {bold('Which concept do you want to branch?')}")
                for i, (t, _) in enumerate(failed, 1):
                    print(f"    {cyan(str(i))}  {t}")
                sub = ask("Choice", "1").lower()
                try:
                    idx = int(sub) - 1
                    if 0 <= idx < len(failed):
                        target = failed[idx]
                    else:
                        print(f"  {yellow('Invalid choice.')}\n")
                        continue
                except ValueError:
                    print(f"  {yellow('Invalid choice.')}\n")
                    continue

            target_title, target_url = target
            run_branch_for_concept(anchor_url, target_title, target_url, perms)
            current_pool = [target]  # loop will re-check this concept next iteration
            continue

        if choice == "a":
            retry_list = list(failed)
        else:
            try:
                idx = int(choice) - 1
                if 0 <= idx < len(failed):
                    retry_list = [failed[idx]]
                else:
                    print(f"  {yellow('Invalid choice — skipping retry.')}\n")
                    return
            except ValueError:
                print(f"  {yellow('Invalid choice — skipping retry.')}\n")
                return

        # Default next cap is a bit higher than the last attempt, max 50.
        default_cap = min(max(last_cap + 10, 25), 50)
        new_cap = ask_int("New hop cap for stage 2 (anchor → concept)", default=default_cap, lo=15, hi=50)
        last_cap = new_cap
        print()

        for title, url in retry_list:
            print(f"\n  {dim('Retrying:')} {bold(title)} {dim(f'(stage 2 cap = {new_cap})')}")
            cmd = [_venv_python(), "-m", "src.path_finder", "one",
                   "--place", _place_for_anchor(anchor_url),
                   "--anchor", anchor_url,
                   "--concept", url,
                   "--permutations", str(perms),
                   "--stage2-hops", str(new_cap),
                   "--allow-duplicates"]
            subprocess.run(cmd, cwd=SCRIPT_DIR)

        # Loop: next pass only checks the retry list. If any still incomplete,
        # we offer another round with an even bigger cap.
        current_pool = retry_list


def run_branch_for_concept(anchor_url: str, concept_title: str, concept_url: str, perms: int) -> None:
    """Branch sub-flow: try alternate anchors on the same place as bridges
    to reach a stubborn concept. Loops until success, exhaustion, or skip."""
    place_url = _place_for_anchor(anchor_url)
    place_title = _place_title_for_url(place_url)
    tried: set[str] = set()  # branch-anchor URLs we've already attempted this round

    while True:
        candidates = _other_anchors_on_place(place_url, anchor_url, tried)

        # Build menu
        header = f"Branch through which anchor on {place_title}?"
        print(f"\n  {bold(header)}")
        for i, a in enumerate(candidates, 1):
            node_type = a.get("node_type") or "?"
            print(f"    {cyan(str(i))}  {a['title']}  {dim('(' + node_type + ')')}")
        print(f"    {cyan('n')}  + Add a new anchor and try with that")
        print(f"    {cyan('s')}  Stop trying to branch")

        sub = ask("Choice", "s").lower()
        if sub in ("s", "stop", ""):
            print("  Stopping branch attempts.\n")
            return

        if sub == "n":
            new_a = inline_add_anchor(prefilled_place_url=place_url, prefilled_place_title=place_title)
            if not new_a or not new_a.get("wikipedia_url"):
                continue
            branch_url = new_a["wikipedia_url"]
            branch_title = new_a.get("title") or branch_url
        else:
            try:
                idx = int(sub) - 1
                if not (0 <= idx < len(candidates)):
                    print(f"  {yellow('Invalid choice.')}\n")
                    continue
                branch_url = candidates[idx]["wikipedia_url"]
                branch_title = candidates[idx]["title"]
            except ValueError:
                print(f"  {yellow('Invalid choice.')}\n")
                continue

        tried.add(branch_url)
        print(f"\n  {dim('Branching:')} {bold(concept_title)} {dim(f'via {branch_title}')}")
        cmd = [_venv_python(), "-m", "src.path_finder", "branched",
               "--place",         place_url,
               "--anchor",        anchor_url,
               "--branch-anchor", branch_url,
               "--concept",       concept_url,
               "--permutations",  str(perms)]
        subprocess.run(cmd, cwd=SCRIPT_DIR)

        # Check whether the concept now has a completed path
        if _concept_completed_count(anchor_url, concept_url) > 0:
            print(f"\n  {green('✓')} {bold(concept_title)} {green('reached via branch.')}\n")
            return

        print(f"\n  {yellow('Still no completed path. Try another branch?')}")


def _other_anchors_on_place(place_url: str, exclude_anchor_url: str, exclude_extra: set[str]) -> list[dict]:
    """Return anchors on the given place, excluding the primary anchor and any
    branch anchors we've already tried this round."""
    rows = fetch_anchors(place_url)
    return [
        a for a in rows
        if a.get("wikipedia_url") != exclude_anchor_url
        and a.get("wikipedia_url") not in exclude_extra
    ]


def _place_title_for_url(place_url: str) -> str:
    for p in fetch_places():
        if p.get("wikipedia_url") == place_url:
            return p.get("title", "")
    return ""


def _concept_completed_count(anchor_url: str, concept_url: str) -> int:
    """Number of completed paths from this anchor → concept in the database.
    Since incomplete paths are no longer saved, this is just the count of rows
    matching (anchor, concept). Returns 0 if anchor or concept node is unknown."""
    result = subprocess.run(
        [_venv_python(), "-c", f"""
import sys
sys.path.insert(0, '.')
from dotenv import load_dotenv; load_dotenv(override=True)
from src.path_finder import sb
anchor_node = sb.table('nodes').select('id').eq('wikipedia_url', {anchor_url!r}).execute()
concept_node = sb.table('nodes').select('id').eq('wikipedia_url', {concept_url!r}).execute()
if not anchor_node.data or not concept_node.data:
    print('0'); sys.exit()
anchor = sb.table('anchors').select('id').eq('node_id', anchor_node.data[0]['id']).execute()
if not anchor.data:
    print('0'); sys.exit()
paths = sb.table('paths').select('id').eq('anchor_id', anchor.data[0]['id']).eq('concept_node_id', concept_node.data[0]['id']).eq('completed', True).execute()
print(len(paths.data))
"""], cwd=SCRIPT_DIR, capture_output=True, text=True,
    )
    out = (result.stdout or "").strip().splitlines()
    if not out:
        return 0
    try:
        return int(out[-1])
    except Exception:
        return 0


def _place_for_anchor(anchor_url: str) -> str:
    """Look up the place URL for an anchor."""
    for a in fetch_anchors():
        if a["wikipedia_url"] == anchor_url:
            return a.get("place_wikipedia_url", "")
    return ""


# ── main menu ───────────────────────────────────────────────────────────────

def main() -> None:
    print(BANNER)
    print(TIP)

    while True:
        print(f"  {bold('What would you like to do?')}")
        print(f"    {cyan('1')}  Create new path            {dim('(Place → Anchor → Concept)')}")
        print(f"    {cyan('2')}  Create new indirect path   {dim('(Place → Anchor → Branch → Concept)')}")
        print(f"    {cyan('3')}  Add an anchor              {dim('(pin a person/place/thing on a map)')}")
        print(f"    {cyan('4')}  List anchors")
        print(f"    {cyan('q')}  Quit")
        print()

        choice = ask("Choice", "1").lower()
        if choice in ("1", ""):
            action_find_paths()
        elif choice == "2":
            action_create_indirect_path()
        elif choice == "3":
            action_add_anchor()
        elif choice == "4":
            action_list_anchors()
        elif choice in ("q", "quit", "exit"):
            print("  Bye.\n")
            return
        else:
            print(f"  {yellow('Unknown choice.')}\n")


if __name__ == "__main__":
    main()
