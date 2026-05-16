# Jeremy's setup guide — Field Trips path-finder

This guide gets you from zero to running the Wikipedia path-finder on your own laptop and contributing paths to the shared Supabase database. Should take about 20 minutes.

---

## What you'll be setting up

- A Python script that walks the Wikipedia link graph between two articles, with Claude picking each hop
- A Claude Code skill (`/path-finder`) that lets you trigger runs conversationally
- Both of these write to the same Supabase database Sarah uses, so you're building the same dataset

---

## Prerequisites

You need three things installed before starting:

### 1. Python 3.12+

Check what you have:
```bash
python3 --version
```

If it says 3.12 or higher, you're good. If not, install from [python.org/downloads](https://python.org/downloads) — get the latest 3.12.x or 3.13.x. On Mac, Homebrew also works:
```bash
brew install python@3.12
```

### 2. Git

```bash
git --version
```

Comes pre-installed on Mac. If missing, Xcode Command Line Tools will install it:
```bash
xcode-select --install
```

### 3. Claude Code

Install the CLI:
```bash
npm install -g @anthropic-ai/claude-code
```

Then sign in:
```bash
claude
```

It'll open a browser to authenticate with your Anthropic account. Follow the prompts.

---

## Step 1: Clone the repo

```bash
cd ~/field-trips        # or wherever you want to keep it
git clone https://github.com/Field-Trips/path-finder.git
cd path-finder
```

> If you get a permissions error, Sarah needs to add you as a collaborator on the `Field-Trips` GitHub org. Ask her.

---

## Step 2: Python environment

```bash
python3.12 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

To verify it worked:
```bash
python -m src.path_finder --help
```

You should see the CLI help text. If you see an error about missing packages, make sure the venv is active (`source .venv/bin/activate`) and try `pip install -r requirements.txt` again.

---

## Step 3: Environment variables (secrets)

```bash
cp .env.example .env
```

Open `.env` in any editor and fill in the two blank values:

```
ANTHROPIC_API_KEY=<your key — get from console.anthropic.com → API keys>
SUPABASE_SERVICE_ROLE_KEY=<ask Sarah — she'll send it to you>
```

Everything else in `.env` is pre-filled. Don't change `SUPABASE_URL` or `DB_SCHEMA`.

> **Security note:** `.env` is gitignored and will never be committed. Keep the service role key out of Slack/email — send it via iMessage or Signal.

---

## Step 4: Verify the database connection

```bash
python -c "
from dotenv import load_dotenv; load_dotenv(override=True)
import os
from supabase import create_client
from supabase.client import ClientOptions
sb = create_client(os.environ['SUPABASE_URL'], os.environ['SUPABASE_SERVICE_ROLE_KEY'], options=ClientOptions(schema='path_finder'))
result = sb.table('nodes').select('id,title').limit(5).execute()
print('Connected! Sample nodes:')
for n in result.data:
    print(f'  {n[\"id\"]}: {n[\"title\"]}')
"
```

You should see a few node titles printed. If you get an auth error, double-check `SUPABASE_SERVICE_ROLE_KEY` in `.env`.

---

## Step 5: Run a path (command line)

```bash
python -m src.path_finder one --start "Monhegan" --end "Conservation movement" --permutations 1
```

This should print something like:
```
[1] ✓  via coastal island ecology
    Monhegan, Maine → Protected area → Conservation movement
```

And you'll see those nodes/paths appear in the shared Supabase database. Check the Table Editor at [supabase.com/dashboard/project/vjikcsifkvphuiwjrmqi](https://supabase.com/dashboard/project/vjikcsifkvphuiwjrmqi) — look under the `path_finder` schema.

---

## Step 6: Install the Claude Code skill

The `/path-finder` skill lets you trigger runs conversationally inside Claude Code instead of typing raw CLI commands.

### 6a. Get the skill file

The skill file is at `path-finder.skill` in the repo root. If it's not there yet, ask Sarah to export it from her Claude Code session.

### 6b. Install it

Open Claude Code in the path-finder directory:
```bash
cd ~/field-trips/path-finder
claude
```

Then in the Claude Code session, drag and drop `path-finder.skill` into the chat, or run:
```
/install-skill path-finder.skill
```

### 6c. Use it

Once installed, just say:
```
/path-finder
```

Claude will ask you for:
- **Start page** — any Wikipedia article title (e.g. "Monhegan", "Textile", "John Muir")
- **End page** — any Wikipedia article title (e.g. "Conservation movement", "Capitalism")
- **Permutations** — how many distinct paths to generate (start with 1 to test, 3 for a real run)

It runs the script, prints the paths, and everything is saved to the database automatically.

---

## Troubleshooting

**`Wikipedia page not found: 'X'`**
The title has to match Wikipedia exactly (case-sensitive after the first letter). Google the article and copy the title from the browser tab.

**`Claude returned 'X', not in candidate list`**
This is a rare Claude mis-step. Just re-run — it'll pick a different hop.

**`SUPABASE_SERVICE_ROLE_KEY` / auth errors**
Make sure `.env` has no leading/trailing spaces around the key value, and that `SUPABASE_URL` is `https://vjikcsifkvphuiwjrmqi.supabase.co` (no `/rest/v1/` at the end).

**Hop cap hit (`×`)** 
The default is 10 hops. For distant topics, increase it:
```bash
python -m src.path_finder one --start "X" --end "Y" --max-hops 15
```

**`source .venv/bin/activate` not working (Windows)**
Use `.venv\Scripts\activate` instead. Python on Windows also needs `py -3.12` instead of `python3.12`.

---

## What the database looks like

All path-finder data lives in the `path_finder` schema on Supabase. Three tables:

- **`nodes`** — every Wikipedia page touched. Has `title`, `node_type` (place/idea/person/event/thing), `intro_text`, `image_url`, `wikipedia_url`.
- **`paths`** — one row per run. Has `start_node_id`, `end_node_id`, `total_hops`, `theme`, `completed`.
- **`edges`** — one row per hop. Ordered by `position_in_path`.

You can browse it in the Supabase dashboard Table Editor, or run SQL in the SQL editor. Some useful queries are in the main `README.md`.

---

## Contributing scenarios

Once you're running, the most useful thing is adding diverse `(start, end)` pairs. Good pairs:
- Start on something local/physical (Monhegan, a specific lighthouse, a textile mill)
- End on something conceptual (a movement, an ideology, an economic system)
- The more interesting the conceptual distance, the more interesting the paths

Run 3 permutations per pair to get route diversity. The database builds up over time into a map of how physical places connect to broader histories.

---

## Questions?

Ask Sarah, or open an issue on the GitHub repo.
