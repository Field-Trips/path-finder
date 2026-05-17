#!/usr/bin/env python3
"""
Field Trips path-finder — interactive runner.

Just run:  python run.py
No flags, no Claude Code needed.
"""

import subprocess
import sys
import os

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


def ask(prompt: str, default: str = "") -> str:
    hint = f" [{default}]" if default else ""
    try:
        val = input(f"  {bold('→')} {prompt}{hint}: ").strip()
    except (KeyboardInterrupt, EOFError):
        print("\n\nCancelled.")
        sys.exit(0)
    return val if val else default


def ask_yes_no(prompt: str, default: bool = False) -> bool:
    hint = "[Y/n]" if default else "[y/N]"
    raw = ask(f"{prompt} {hint}").lower()
    if not raw:
        return default
    return raw in ("y", "yes")


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
    """
    Interactively prompt for a Wikipedia title or URL, validate it exists,
    detect disambiguation, and return (resolved_title, resolved_url).
    """
    script_dir = os.path.dirname(os.path.abspath(__file__))
    venv_python = _venv_python(script_dir)

    while True:
        raw = ask(f"{label} article — title or Wikipedia URL")
        if not raw:
            print(f"     {yellow('Required.')}")
            continue

        print(f"     {dim('Checking Wikipedia...')}", end="\r")
        result = subprocess.run(
            [venv_python, "-c", f"""
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
            cwd=script_dir,
            capture_output=True, text=True
        )

        print("                                    ", end="\r")  # clear "Checking" line

        try:
            import json
            data = json.loads(result.stdout.strip().splitlines()[-1])
        except Exception:
            print(f"     {red('Unexpected error:')} {result.stderr[:200]}")
            continue

        if data.get("ok"):
            title = data["title"]
            url   = data["url"]
            intro = data.get("intro", "")
            print(f"     {green('✓')} {bold(title)}")
            if intro:
                print(f"     {dim(intro + '...')}")
            print()
            return title, url

        if data.get("disambiguation"):
            print(f"     {yellow('Disambiguation page')} — that title matches multiple articles:")
            for opt in (data.get("options") or [])[:8]:
                print(f"       {dim('•')} {opt}")
            print(f"     {dim('Go to Wikipedia, find the exact article, and paste the URL.')}")
            print()
            continue

        print(f"     {red('Not found:')} {data.get('msg', 'unknown error')}")
        print()


def _venv_python(script_dir: str) -> str:
    venv = os.path.join(script_dir, ".venv", "bin", "python")
    if not os.path.exists(venv):
        venv = os.path.join(script_dir, ".venv", "Scripts", "python.exe")
    if not os.path.exists(venv):
        print(red("\n  Error: virtual environment not found."))
        print("  Run:  python3 -m venv .venv && source .venv/bin/activate && pip install -r requirements.txt")
        sys.exit(1)
    return venv


def run_path_finder(start_url: str, place_url: str, perms: int) -> None:
    script_dir = os.path.dirname(os.path.abspath(__file__))
    venv_python = _venv_python(script_dir)

    cmd = [
        venv_python, "-m", "src.path_finder", "one",
        "--start", start_url,
        "--place", place_url,
        "--permutations", str(perms),
    ]

    print(f"\n  {dim('Running … (Ctrl+C to stop)')}\n")
    print("  " + "─" * 50)
    result = subprocess.run(cmd, cwd=script_dir)
    print("  " + "─" * 50)

    if result.returncode == 0:
        print(f"\n  {green('Done.')} Paths saved to the Field Trips database.\n")
    else:
        print(f"\n  {red('Something went wrong')} — see the error above.\n")
        print(f"  {dim('Common fixes:')}")
        print(f"  {dim('  • Typo? Paste the Wikipedia URL instead of a title.')}")
        print(f"  {dim('  • Missing key? Check your .env file.')}")


def main() -> None:
    print(BANNER)
    print(TIP)

    # ── object article ───────────────────────────────────────────────────────
    start_title, start_url = resolve_article("Object")

    # ── place article ────────────────────────────────────────────────────────
    print(f"  {dim('What place does')} {bold(start_title)} {dim('belong to?')}")
    print(f"  {dim('This is where the path will end (e.g. \"Monhegan Island\", \"Maine\", \"New York City\").')}")
    print()
    place_title, place_url = resolve_article("Place")

    # ── permutations ─────────────────────────────────────────────────────────
    print(f"  {bold('How many distinct paths?')}  {dim('1 = quick · 3 = standard · 5 = thorough')}")
    perms = ask_int("Permutations", default=1, lo=1, hi=10)
    print()

    # ── confirm ──────────────────────────────────────────────────────────────
    print(f"  {bold('Ready to run:')}")
    print(f"    Object      {green(start_title)}")
    print(f"    Place       {green(place_title)}")
    print(f"    Paths       {green(str(perms))}")
    print(f"\n  {dim('Each path takes ~30–90 s. All results save to Supabase automatically.')}\n")

    try:
        go = input(f"  {bold('→')} Go? [Y/n]: ").strip().lower()
    except (KeyboardInterrupt, EOFError):
        print("\n\nCancelled.")
        sys.exit(0)

    if go not in ("", "y", "yes"):
        print("  Cancelled.\n")
        sys.exit(0)

    run_path_finder(start_url, place_url, perms)


if __name__ == "__main__":
    main()
