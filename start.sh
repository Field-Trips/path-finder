#!/usr/bin/env bash
# Field Trips path-finder — one-shot start.
# Pulls the latest code, sanity-checks your environment, then runs the script.
#
# Usage:   ~/field-trips/path-finder/start.sh
# Or set an alias:  alias pathfinder="~/field-trips/path-finder/start.sh"
# Then just type:   pathfinder

set -e
SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
cd "$SCRIPT_DIR"

# ── sanity checks ───────────────────────────────────────────────────────────
MISSING=0
if [ ! -d ".venv" ]; then
  echo "❌  Virtual environment missing."
  echo "    Run: python3 -m venv .venv && source .venv/bin/activate && pip install -r requirements.txt"
  MISSING=1
fi

if [ ! -f ".env" ]; then
  echo "❌  .env file missing."
  echo "    Run: cp .env.example .env && open -e .env"
  echo "    Then add ANTHROPIC_API_KEY and SUPABASE_SERVICE_ROLE_KEY."
  MISSING=1
fi

if [ "$MISSING" = "1" ]; then
  echo ""
  echo "Fix the issues above, then re-run this script."
  exit 1
fi

# ── pull latest ─────────────────────────────────────────────────────────────
echo "📡  Pulling latest code from git..."
if ! git pull --rebase --autostash 2>&1; then
  echo "⚠   git pull failed — continuing with your local version."
fi
echo ""

# ── run ─────────────────────────────────────────────────────────────────────
echo "🚀  Starting path-finder..."
echo ""
python3 run.py
