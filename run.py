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


def pick_anchor() -> dict:
    """Show existing anchors; user picks one or adds new. Returns full anchor record."""
    anchors = fetch_anchors()
    if not anchors:
        print(f"  {dim('No anchors saved yet — adding a new one.')}")
        return inline_add_anchor()

    print(f"\n  {bold('Pick an anchor:')}")
    for i, a in enumerate(anchors, 1):
        place = a.get("place_title") or "?"
        node_type = a.get("node_type") or "?"
        print(f"    {cyan(str(i))}  {a['title']}  {dim(f'({node_type} · on {place})')}")
    print(f"    {cyan('n')}  + Add new anchor")

    while True:
        choice = ask("Choice", "1").lower()
        if choice == "n":
            return inline_add_anchor()
        try:
            idx = int(choice) - 1
            if 0 <= idx < len(anchors):
                a = anchors[idx]
                print(f"     {green('✓')} {bold(a['title'])} on {bold(a.get('place_title') or '?')}\n")
                return a
        except ValueError:
            pass
        print(f"     {yellow('Please pick a number or n.')}")


def inline_add_anchor() -> dict:
    """Add a new anchor and return its record so it can flow into the next step."""
    print(f"\n  {bold('Add a new anchor')}")
    print(f"  {dim('An anchor is a person/place/thing pinned on the map of a place.')}\n")

    place_title, place_url = pick_place()
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
    """Collect 1-5 concepts, one per line. Each is validated against Wikipedia.
    Blank line finishes the list. Returns list of (title, url) tuples."""
    print(f"\n  {bold('Concepts')}")
    print(f"  {dim('Enter one Wikipedia title or URL per line. Blank line to finish. Max 5.')}\n")

    out: list[tuple[str, str]] = []
    while len(out) < 5:
        n = len(out) + 1
        label = f"Concept #{n}"
        raw = ask(f"{label} (Wikipedia title or URL, blank to {'finish' if out else 'cancel'})", "")
        if not raw:
            if out:
                break
            return []
        # Validate
        title, url = _validate_wikipedia(raw)
        if title:
            out.append((title, url))
    if len(out) == 5:
        print(f"  {dim('Reached 5-concept cap (rate limit guidance).')}\n")
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
    print(f"\n  {bold('Find paths')}")
    print(f"  {dim('Pick an anchor, then say what concept you want to connect it to.')}\n")

    anchor = pick_anchor()
    if not anchor:
        return

    anchor_title = anchor["title"]
    anchor_url   = anchor["wikipedia_url"]
    place_title  = anchor.get("place_title") or "?"
    place_url    = anchor.get("place_wikipedia_url") or ""

    if not place_url:
        # Shouldn't happen, but guard anyway
        place_title, place_url = pick_place()

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


# ── main menu ───────────────────────────────────────────────────────────────

def main() -> None:
    print(BANNER)
    print(TIP)

    while True:
        print(f"  {bold('What would you like to do?')}")
        print(f"    {cyan('1')}  Find paths        {dim('(Place → Anchor → Concept)')}")
        print(f"    {cyan('2')}  Add an anchor     {dim('(pin a person/place/thing on a map)')}")
        print(f"    {cyan('3')}  List anchors")
        print(f"    {cyan('q')}  Quit")
        print()

        choice = ask("Choice", "1").lower()
        if choice in ("1", ""):
            action_find_paths()
        elif choice == "2":
            action_add_anchor()
        elif choice == "3":
            action_list_anchors()
        elif choice in ("q", "quit", "exit"):
            print("  Bye.\n")
            return
        else:
            print(f"  {yellow('Unknown choice.')}\n")


if __name__ == "__main__":
    main()
