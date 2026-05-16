#!/usr/bin/env python3
"""
Field Trips path-finder — interactive runner.

Just run:  python run.py
No flags, no Claude Code, no skill needed.
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

BANNER = f"""
{bold("╔══════════════════════════════════════════╗")}
{bold("║    Field Trips — Wikipedia Path-Finder   ║")}
{bold("╚══════════════════════════════════════════╝")}

Finds how two Wikipedia articles connect through
their internal links. Results are saved to the
shared Field Trips database automatically.
"""

EXAMPLES = dim("""\
  Examples of good pairs
  ─────────────────────
  Start: Monhegan           →  End: Conservation movement
  Start: Lowell Mills       →  End: Labor movement
  Start: John Singer Sargent →  End: Modernism
  Start: Weaving            →  End: Industrial Revolution
""")


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


def confirm(start: str, end: str, perms: int) -> bool:
    print(f"""
  {bold('Ready to run:')}
    Start       {green(start)}
    End         {green(end)}
    Paths       {green(str(perms))}

  {dim('Each path takes ~30–90 seconds. Results go to Supabase automatically.')}
""")
    try:
        ans = input(f"  {bold('→')} Go? [Y/n]: ").strip().lower()
    except (KeyboardInterrupt, EOFError):
        print("\n\nCancelled.")
        sys.exit(0)
    return ans in ("", "y", "yes")


def run_path_finder(start: str, end: str, perms: int) -> None:
    script_dir = os.path.dirname(os.path.abspath(__file__))
    venv_python = os.path.join(script_dir, ".venv", "bin", "python")

    # On Windows the venv layout is different
    if not os.path.exists(venv_python):
        venv_python = os.path.join(script_dir, ".venv", "Scripts", "python.exe")

    if not os.path.exists(venv_python):
        print(red("\n  Error: virtual environment not found."))
        print("  Run:  python3 -m venv .venv && source .venv/bin/activate && pip install -r requirements.txt")
        sys.exit(1)

    cmd = [
        venv_python, "-m", "src.path_finder", "one",
        "--start", start,
        "--end", end,
        "--permutations", str(perms),
    ]

    print(f"\n  {dim('Running … (press Ctrl+C to stop)')}\n")
    print("  " + "─" * 50)

    result = subprocess.run(cmd, cwd=script_dir)

    print("  " + "─" * 50)

    if result.returncode == 0:
        print(f"\n  {green('✓')} Done! Paths saved to the Field Trips database.")
    else:
        print(f"\n  {red('✗')} Something went wrong. See the error above.")
        print(f"  {dim('Common fixes:')}")
        print(f"  {dim('  - Typo in a Wikipedia title? Try copying it from the browser tab.')}")
        print(f"  {dim('  - Missing API key? Check your .env file.')}")


def main() -> None:
    print(BANNER)
    print(EXAMPLES)

    start = ""
    while not start:
        start = ask("Start Wikipedia article")
        if not start:
            print(f"     {yellow('Start article is required.')}")

    end = ""
    while not end:
        end = ask("End Wikipedia article")
        if not end:
            print(f"     {yellow('End article is required.')}")

    print(f"""
  {bold('How many distinct paths?')}
  {dim('1 = quick (30–90 s)   3 = standard   5 = thorough (several minutes)')}""")
    perms = ask_int("Permutations", default=1, lo=1, hi=10)

    print()
    if not confirm(start, end, perms):
        print("  Cancelled.\n")
        sys.exit(0)

    run_path_finder(start, end, perms)
    print()


if __name__ == "__main__":
    main()
