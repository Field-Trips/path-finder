#!/usr/bin/env bash
# Field Trips path-finder — environment diagnostic
# Run this and paste the output to Sarah.
# Nothing is sent anywhere — it only prints to your screen.

SEP="────────────────────────────────────────────────"
PASS="✅"
WARN="⚠️ "
FAIL="❌"

echo ""
echo "Field Trips path-finder — environment check"
echo "$SEP"
echo "Run date: $(date)"
echo "Machine:  $(uname -sm)"
echo "$SEP"
echo ""

# ── 1. Operating system ─────────────────────────────────────────────────────
echo "── 1. Operating system"
sw_vers 2>/dev/null || uname -a
echo ""

# ── 2. Terminal / shell ──────────────────────────────────────────────────────
echo "── 2. Shell"
echo "  Shell: $SHELL"
echo "  PATH entries:"
echo "$PATH" | tr ':' '\n' | sed 's/^/    /'
echo ""

# ── 3. Python ────────────────────────────────────────────────────────────────
echo "── 3. Python"
for cmd in python python3 python3.12 python3.13 python3.14; do
  if command -v "$cmd" &>/dev/null; then
    ver=$("$cmd" --version 2>&1)
    loc=$(command -v "$cmd")
    echo "  $PASS $cmd → $ver  ($loc)"
  fi
done
if ! command -v python3 &>/dev/null && ! command -v python &>/dev/null; then
  echo "  $FAIL No Python found"
fi
echo ""

# ── 4. pip ───────────────────────────────────────────────────────────────────
echo "── 4. pip"
for cmd in pip pip3 pip3.12; do
  if command -v "$cmd" &>/dev/null; then
    ver=$("$cmd" --version 2>&1)
    echo "  $PASS $cmd → $ver"
  fi
done
echo ""

# ── 5. Git ───────────────────────────────────────────────────────────────────
echo "── 5. Git"
if command -v git &>/dev/null; then
  echo "  $PASS $(git --version)"
  echo "  Location: $(command -v git)"
  echo "  Git user.name:  $(git config --global user.name 2>/dev/null || echo '(not set)')"
  echo "  Git user.email: $(git config --global user.email 2>/dev/null || echo '(not set)')"
else
  echo "  $FAIL Git not found"
fi
echo ""

# ── 6. GitHub SSH / HTTPS auth ───────────────────────────────────────────────
echo "── 6. GitHub access"
if ssh -T git@github.com -o StrictHostKeyChecking=no -o ConnectTimeout=5 2>&1 | grep -q "successfully authenticated"; then
  echo "  $PASS SSH key authenticated with GitHub"
else
  echo "  $WARN SSH auth not set up (HTTPS clone will still work)"
fi
echo ""

# ── 7. Homebrew (Mac only) ───────────────────────────────────────────────────
echo "── 7. Homebrew"
if command -v brew &>/dev/null; then
  echo "  $PASS $(brew --version | head -1)"
else
  echo "  $WARN Homebrew not installed (helpful but not required)"
fi
echo ""

# ── 8. Node / npm (needed to install Claude Code — optional) ─────────────────
echo "── 8. Node.js / npm"
if command -v node &>/dev/null; then
  echo "  $PASS node $(node --version)  ($(command -v node))"
else
  echo "  $WARN Node not found (only needed if you want the optional Claude Code skill)"
fi
if command -v npm &>/dev/null; then
  echo "  $PASS npm $(npm --version)"
fi
echo ""

# ── 9. Existing path-finder repo ─────────────────────────────────────────────
echo "── 9. path-finder repo"
SEARCH_DIRS=("$HOME" "$HOME/Documents" "$HOME/Desktop" "$HOME/field-trips" "$HOME/dev" "$HOME/code")
FOUND_REPO=""
for d in "${SEARCH_DIRS[@]}"; do
  if [ -f "$d/path-finder/src/path_finder.py" ]; then
    FOUND_REPO="$d/path-finder"
    break
  fi
done
if [ -n "$FOUND_REPO" ]; then
  echo "  $PASS Repo found at: $FOUND_REPO"
  if [ -d "$FOUND_REPO/.venv" ]; then
    echo "  $PASS .venv exists"
    if "$FOUND_REPO/.venv/bin/python" -c "import supabase, anthropic, dotenv" 2>/dev/null; then
      echo "  $PASS Python dependencies installed"
    else
      echo "  $WARN Python dependencies not fully installed"
    fi
  else
    echo "  $WARN .venv not set up yet"
  fi
  if [ -f "$FOUND_REPO/.env" ]; then
    if grep -qE "ANTHROPIC_API_KEY\s*=\s*sk-" "$FOUND_REPO/.env" 2>/dev/null; then
      echo "  $PASS ANTHROPIC_API_KEY is set"
    else
      echo "  $FAIL ANTHROPIC_API_KEY missing or blank"
    fi
    if grep -qE "SUPABASE_SERVICE_ROLE_KEY\s*=\s*eyJ" "$FOUND_REPO/.env" 2>/dev/null; then
      echo "  $PASS SUPABASE_SERVICE_ROLE_KEY is set"
    else
      echo "  $FAIL SUPABASE_SERVICE_ROLE_KEY missing or blank"
    fi
  else
    echo "  $WARN .env file not found"
  fi
else
  echo "  $WARN path-finder repo not found in common locations"
fi
echo ""

# ── 10. Internet & Anthropic API reachability ────────────────────────────────
echo "── 10. Network"
if curl -s --max-time 5 https://api.anthropic.com > /dev/null 2>&1; then
  echo "  $PASS api.anthropic.com reachable"
else
  echo "  $FAIL api.anthropic.com unreachable (check internet connection)"
fi
if curl -s --max-time 5 https://vjikcsifkvphuiwjrmqi.supabase.co > /dev/null 2>&1; then
  echo "  $PASS Supabase project reachable"
else
  echo "  $FAIL Supabase project unreachable"
fi
echo ""

echo "$SEP"
echo "Done. Please copy everything above and send it to Sarah."
echo "$SEP"
echo ""
