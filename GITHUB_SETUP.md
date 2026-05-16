# Setup — picking up from your current state

You've already got the foundation: git installed and configured, `gh` CLI authenticated as `sarahedoyal`, Python 3.12 installed, Node + npm, Claude Code. Your GitHub org is `Field-Trips`, your Supabase project is `field-trips` (URL: `https://vjikcsifkvphuiwjrmqi.supabase.co`). This guide walks you through everything that's still ahead.

If anything looks off, the audit script from earlier is the source of truth — re-run it any time you want to confirm state.

> **Mental model:** code lives in two places — *local* (your Mac) and *remote* (github.com). `git commit` saves a snapshot locally. `git push` sends snapshots to remote. `git pull` brings them back.

---

## Step 1 — Create the repo on GitHub

Since `gh` is authenticated, this is one command. Run it from anywhere:

```bash
gh repo create Field-Trips/path-finder \
  --private \
  --description "Agentic Wikipedia path finder for Field Trips"
```

**Check:**

```bash
gh repo view Field-Trips/path-finder
```

Should print the repo's metadata (description, visibility, etc.). If you see "Could not resolve to a Repository," the create command didn't run successfully.

---

## Step 2 — Clone it into ~/field-trips

You're already working out of `/Users/sarah/field-trips/`, so the natural place for this repo is right inside that folder.

```bash
cd ~/field-trips
git clone https://github.com/Field-Trips/path-finder.git
cd path-finder
```

You'll see `warning: You appear to have cloned an empty repository.` — that's correct; we just made it empty on purpose.

**Check:**

```bash
pwd
```

Should print `/Users/sarah/field-trips/path-finder`.

```bash
ls -la
```

Should show `.git/` and nothing else.

---

## Step 3 — Copy the starter files in

The simplest path: have Claude Code do it. From inside `~/field-trips/path-finder`:

```bash
claude
```

Then ask:

> Copy every file from `/Users/sarah/Library/Application Support/Claude/local-agent-mode-sessions/55d41dc2-7c4b-4ea6-969f-aba338ff0c4b/0d740404-de86-4f6f-b1a1-e9f0f79611f7/local_4790dc26-31fe-4cde-9926-7b49c99e3ee3/outputs/path-finder/` into the current directory, preserving the subfolder structure (`supabase/`, `src/`).

Claude Code will handle it. Exit with `Ctrl+D` or `/exit` when done.

**Alternative (Finder drag-and-drop):** in any Cowork message that includes a `computer://` link, right-click the link → **Reveal in Finder**. Navigate up one level to the `path-finder/` folder. Select everything inside (`Cmd+A`), drag into your local `~/field-trips/path-finder/`.

**Check:**

```bash
ls -la
```

Should show:

```
.gitignore        .env.example      README.md
GITHUB_SETUP.md   requirements.txt  scenarios.example.yaml
supabase/         src/
```

---

## Step 4 — First commit and push

```bash
git status                          # red files under "Untracked"
git add .                           # stage them all
git status                          # now green under "Changes to be committed"
git commit -m "Initial scaffold"
git branch -M main                  # make sure the branch is named "main"
git push -u origin main             # send to GitHub; -u is one-time
```

**Check:** refresh `https://github.com/Field-Trips/path-finder` in your browser. You should see all your files.

---

## Step 5 — Python virtualenv and dependencies

```bash
python3.12 -m venv .venv             # creates a private Python env in this folder
source .venv/bin/activate            # activates it — your prompt now starts with (.venv)
pip install -r requirements.txt      # installs anthropic, supabase, requests, etc.
```

Notice the `python3.12` — use the version you just installed, not the bare `python3` which still points at system 3.9.

**Check:**

```bash
which python
```

Should print something inside `.venv/bin/`, not `/usr/bin/`.

```bash
python -c "import anthropic, supabase, requests, yaml, click, dotenv; print('all imports ok')"
```

Should print `all imports ok`.

To leave the venv later: `deactivate`. To re-enter it next session: `cd ~/field-trips/path-finder && source .venv/bin/activate`.

---

## Step 6 — Local secrets file

```bash
cp .env.example .env
open -e .env
```

Fill in:

- `ANTHROPIC_API_KEY` — from `console.anthropic.com` → API Keys → Create Key. Starts with `sk-ant-...`. (You only see the full string once at creation.)
- `SUPABASE_SERVICE_ROLE_KEY` — from `https://supabase.com/dashboard/project/vjikcsifkvphuiwjrmqi/settings/api` → "Project API keys" → click **service_role** → copy. (Full DB access; never commit it.)
- `SUPABASE_URL` is pre-filled with your project URL.

Save the file.

**Check:**

```bash
git status
```

`.env` should NOT appear (the `.gitignore` excludes it). If it does, something's off — see the recovery section at the bottom.

---

## Step 7 — Apply the Supabase schema

Two things to do here: run the migration, then expose the new schema in the API settings.

**7a. Run the migration.** Open:

```
https://supabase.com/dashboard/project/vjikcsifkvphuiwjrmqi/sql/new
```

Open `supabase/migrations/0001_initial_schema.sql` in your editor, copy the entire contents, paste into the SQL editor, click **Run**. You should see "Success. No rows returned."

**7b. Expose the schema.** Our tables live in a `path_finder` Postgres schema (kept separate from your existing `public` tables so we don't collide with book-ingest stuff). Supabase only exposes `public` by default, so we need to tell it about ours:

```
Project Settings → API → "Exposed schemas" → add "path_finder" → Save
```

Direct link: `https://supabase.com/dashboard/project/vjikcsifkvphuiwjrmqi/settings/api`

**Check:** open the Table Editor at `https://supabase.com/dashboard/project/vjikcsifkvphuiwjrmqi/editor`, then in the schema dropdown (top-left of the editor) switch from `public` to `path_finder`. You should see three tables: `nodes`, `paths`, `edges`, and a view called `connections`.

---

## Step 8 — Sanity check that the script runs

Still inside the activated venv, in `~/field-trips/path-finder`:

```bash
python -m src.path_finder --help
```

Should print the CLI help (two commands: `one` and `run`). If you see an `ImportError` or `KeyError`, something in the env or imports is off — check `.env` was filled in and the venv is activated.

For a "does Wikipedia and Claude actually work" smoke test (this won't write to Supabase yet because `upsert_node` and `insert_path` are still TODOs):

```bash
python -m src.path_finder one --start "Monhegan" --end "Conservation movement" --permutations 1
```

You should see Claude walk a path from Monhegan to Conservation movement and print it. If it errors, the error message will tell you what's wrong — most commonly an invalid API key or a missing env var.

---

## You're set up

Open Claude Code in `~/field-trips/path-finder` and start vibe-coding the TODO sections in `src/path_finder.py` (see the README). Suggested opening prompt:

> Read `README.md` and `src/path_finder.py`. Implement the `TODO(vibe-code)` sections. Start with `upsert_node` and `insert_path` (so we can actually persist), then improve `pick_next_hop`'s candidate shortlisting.

---

## If something went wrong

**`gh repo create` returned "name already exists"**
Someone (maybe you, earlier) already made it. Confirm with `gh repo view Field-Trips/path-finder` — if it's empty, skip to Step 2. If it has files, ask Claude Code or me before destroying anything.

**`git clone` got `repository not found`**
Either Step 1 didn't actually succeed, or `gh auth status` is no longer logged into the right account. Re-run `gh auth status`.

**"fatal: not a git repository"**
You're in the wrong directory. `cd ~/field-trips/path-finder` and retry.

**`git push` rejected with "remote contains work that you do not have locally"**
This usually means a README or .gitignore was auto-created on GitHub. Fix:
```bash
git pull --rebase origin main
git push
```

**Accidentally committed `.env`**
Critical — rotate secrets first (Anthropic console → revoke key; Supabase → reset service_role). Then ask Claude Code to remove `.env` from git history. Don't manually `git filter-branch` — it's footgun-y.

**`.env` showing up in `git status`**
Either no `.gitignore` (check `ls -la`), or `.env` was added to git before the ignore took effect. Untrack it:
```bash
git rm --cached .env
git commit -m "stop tracking .env"
```

**Supabase Table Editor doesn't show the path_finder schema**
You probably skipped Step 7b. Go to Project Settings → API → Exposed schemas → add `path_finder` → Save → refresh.

**`python -c "import ..."` says ModuleNotFoundError**
Venv isn't activated. Look at your prompt — it should start with `(.venv)`. If not: `source .venv/bin/activate`.

**`python3.12: command not found`**
The python.org installer didn't add it to PATH. Try `/Library/Frameworks/Python.framework/Versions/3.12/bin/python3.12 --version` — if that works, you can either alias it or re-run the installer.

**Pushed something you regret**
Don't `git push --force` to a shared branch — that rewrites history for everyone. Either revert (`git revert <commit>`) or ask Claude Code to walk you through it.

**Confused about which directory you're in**
`pwd` shows where you are. `cd ~/field-trips/path-finder` puts you back home.
