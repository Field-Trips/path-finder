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


# ── actions ─────────────────────────────────────────────────────────────────

def action_add_anchor():
    print(f"\n  {bold('Add anchor')}")
    print(f"  {dim('An anchor is a curated person/place/thing pinned on the map of a place.')}\n")

    place_title, place_url = resolve_article("Place")
    anchor_title, anchor_url = resolve_article("Anchor (person/place/thing)")

    print(f"  {dim('Rationale (optional) — why this anchor belongs to this place. Enter to skip.')}")
    rationale = ask("Rationale", "")
    print(f"  {dim('Custom image URL (optional) — overrides Wikipedia image. Enter to skip.')}")
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
    return result.returncode == 0


def action_list_anchors():
    print(f"\n  {bold('Anchors')}\n")
    place = ask("Filter by place (Wikipedia title/URL, or press Enter for all)", "")
    cmd = [_venv_python(), "-m", "src.path_finder", "anchor", "list"]
    if place:
        cmd += ["--place", place]
    print()
    subprocess.run(cmd, cwd=SCRIPT_DIR)
    print()


def action_find_paths():
    print(f"\n  {bold('Find paths')}")
    print(f"  {dim('Place → Anchor → Concept')}\n")

    place_title,   place_url   = resolve_article("Place")
    anchor_title,  anchor_url  = resolve_article("Anchor")
    concept_title, concept_url = resolve_article("Concept (the destination idea/event)")

    print(f"  {bold('How many distinct paths?')}  {dim('1 = quick · 3 = standard · 5 = thorough')}")
    perms = ask_int("Permutations", default=1, lo=1, hi=10)
    print()

    print(f"  {bold('Ready to run:')}")
    print(f"    Place    {green(place_title)}")
    print(f"    Anchor   {green(anchor_title)}")
    print(f"    Concept  {green(concept_title)}")
    print(f"    Paths    {green(str(perms))}")
    print(f"\n  {dim('Each path takes ~1–3 minutes. Results save to Supabase automatically.')}\n")

    try:
        go = input(f"  {bold('→')} Go? [Y/n]: ").strip().lower()
    except (KeyboardInterrupt, EOFError):
        print("\n\nCancelled.")
        return
    if go not in ("", "y", "yes"):
        print("  Cancelled.\n")
        return

    cmd = [_venv_python(), "-m", "src.path_finder", "one",
           "--place", place_url,
           "--anchor", anchor_url,
           "--concept", concept_url,
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
