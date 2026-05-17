"""
Field Trips path-finder.

Given a (start, end) pair of Wikipedia pages, produce N distinct paths from
start to end by walking the Wikipedia link graph one hop at a time, with
Claude picking each next hop. Persist nodes, paths, and edges to Supabase.

This file is a SKELETON. Function signatures and the main loop are sketched;
fill in the bodies with Claude Code. The TODOs mark the bits that need real
implementation work.

Run:
    python -m src.path_finder run --scenarios scenarios.yaml
    python -m src.path_finder one --start "Monhegan" --end "Conservation movement"
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from typing import Optional
from urllib.parse import quote

import click
import requests
import yaml
from anthropic import Anthropic
from dotenv import load_dotenv
from supabase import Client, create_client
from supabase.client import ClientOptions

load_dotenv(override=True)

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

def _require_env(key: str, hint: str = "") -> str:
    val = os.environ.get(key, "").strip()
    if not val:
        lines = [
            f"\n  ✗  Missing environment variable: {key}",
            "     Add it to your .env file in ~/field-trips/path-finder/",
        ]
        if hint:
            lines.append(f"     {hint}")
        raise SystemExit("\n".join(lines) + "\n")
    # Warn about look-alike Unicode characters (e.g. Cyrillic е instead of Latin e)
    try:
        val.encode("ascii")
    except UnicodeEncodeError:
        raise SystemExit(
            f"\n  ✗  {key} contains a non-ASCII character.\n"
            "     This usually means your Mac's autocorrect replaced a letter\n"
            "     when you pasted the key (e.g. Cyrillic 'е' instead of Latin 'e').\n"
            "     Open .env, delete and re-paste the value with autocorrect off.\n"
        )
    return val

ANTHROPIC_API_KEY = _require_env("ANTHROPIC_API_KEY", "It should start with sk-ant-")
SUPABASE_URL      = _require_env("SUPABASE_URL",      "It should look like https://xxxx.supabase.co")
SUPABASE_SERVICE_ROLE_KEY = _require_env(
    "SUPABASE_SERVICE_ROLE_KEY", "It should start with eyJ — get it from Supabase → Project Settings → API"
)

MAX_HOPS = int(os.environ.get("MAX_HOPS", "10"))
DEFAULT_PERMUTATIONS = int(os.environ.get("DEFAULT_PERMUTATIONS", "3"))
CLAUDE_MODEL = os.environ.get("CLAUDE_MODEL", "claude-sonnet-4-6")

# Postgres schema where our tables live (not `public` — see supabase/migrations/0001_initial_schema.sql)
DB_SCHEMA = os.environ.get("DB_SCHEMA", "path_finder")

WIKI_API = "https://en.wikipedia.org/w/api.php"
WIKI_USER_AGENT = "FieldTripsPathFinder/0.1 (admin@fieldtrips.club)"

NODE_TYPES = ("place", "idea", "person", "event", "thing")


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------

@dataclass
class WikiPage:
    title: str
    url: str
    intro_text: str
    image_url: Optional[str] = None
    links: list[str] = field(default_factory=list)  # titles of internal wikilinks


@dataclass
class Path:
    start_title: str
    end_title: str
    hops: list[str] = field(default_factory=list)   # ordered list of node titles, start to end
    completed: bool = False
    theme: Optional[str] = None


# ---------------------------------------------------------------------------
# Wikipedia (MediaWiki API)
# ---------------------------------------------------------------------------

class DisambiguationError(ValueError):
    """Raised when a Wikipedia title resolves to a disambiguation page."""
    def __init__(self, title: str, options: list[str]):
        self.title = title
        self.options = options
        opts = "\n".join(f"  • {o}" for o in options[:8])
        super().__init__(
            f"{title!r} is a disambiguation page. "
            f"Go to Wikipedia, find the exact article you want, and paste its URL.\n"
            f"Some options:\n{opts}"
        )


def normalize_title(title: str) -> str:
    """'monhegan island' -> 'Monhegan Island'. Wikipedia titles are case-sensitive after the first char."""
    return title.strip().replace("_", " ")


def title_from_url(url: str) -> str:
    """Extract article title from a Wikipedia URL, e.g. https://en.wikipedia.org/wiki/Monhegan_Island"""
    from urllib.parse import urlparse, unquote
    path = urlparse(url).path
    if "/wiki/" not in path:
        raise ValueError(f"Not a recognisable Wikipedia article URL: {url!r}")
    raw = path.split("/wiki/", 1)[1].split("#")[0]  # drop anchors
    return unquote(raw).replace("_", " ")


def wiki_url(title: str) -> str:
    return f"https://en.wikipedia.org/wiki/{quote(normalize_title(title).replace(' ', '_'))}"


def fetch_wiki_page(title_or_url: str) -> WikiPage:
    """
    Fetch a page's intro text, lead image, and internal wikilinks.

    Accepts either a plain title ('Monhegan Island') or a full Wikipedia URL.
    Raises DisambiguationError if the page is a disambiguation page.
    Raises ValueError if the page is not found.
    """
    if title_or_url.startswith("http"):
        title = title_from_url(title_or_url)
    else:
        title = normalize_title(title_or_url)

    headers = {"User-Agent": WIKI_USER_AGENT}

    # 1) Intro extract + lead image + pageprops (to detect disambiguation)
    extract_params = {
        "action": "query",
        "format": "json",
        "prop": "extracts|pageimages|pageprops",
        "exintro": 1,
        "explaintext": 1,
        "piprop": "original",
        "redirects": 1,
        "titles": title,
    }
    r = requests.get(WIKI_API, params=extract_params, headers=headers, timeout=15)
    r.raise_for_status()
    pages = r.json().get("query", {}).get("pages", {})
    page = next(iter(pages.values()), {}) if pages else {}
    if "missing" in page:
        raise ValueError(
            f"Wikipedia page not found: {title!r}\n"
            f"Tip: go to Wikipedia, find the article, and paste the URL instead of the title."
        )
    resolved_title = page.get("title", title)
    intro = page.get("extract", "") or ""
    image_url: Optional[str] = (page.get("original") or {}).get("source")

    # Disambiguation check
    if "disambiguation" in (page.get("pageprops") or {}):
        # Fetch the links on the disambiguation page to show as options
        opts_r = requests.get(WIKI_API, params={
            "action": "query", "format": "json",
            "prop": "links", "pllimit": "20", "plnamespace": 0,
            "redirects": 1, "titles": resolved_title,
        }, headers=headers, timeout=15)
        opts_r.raise_for_status()
        opts_pages = opts_r.json().get("query", {}).get("pages", {})
        opts_page = next(iter(opts_pages.values()), {})
        options = [l["title"] for l in (opts_page.get("links") or [])]
        raise DisambiguationError(resolved_title, options)

    # 2) Internal links (paginated)
    links: list[str] = []
    cont: dict[str, str] = {}
    while True:
        link_params = {
            "action": "query",
            "format": "json",
            "prop": "links",
            "pllimit": "max",
            "plnamespace": 0,        # main namespace only — no Talk:, File:, etc.
            "redirects": 1,
            "titles": resolved_title,
            **cont,
        }
        r = requests.get(WIKI_API, params=link_params, headers=headers, timeout=15)
        r.raise_for_status()
        data = r.json()
        for p in data.get("query", {}).get("pages", {}).values():
            for link in p.get("links", []) or []:
                links.append(link["title"])
        if "continue" in data:
            cont = data["continue"]
        else:
            break

    return WikiPage(
        title=resolved_title,
        url=wiki_url(resolved_title),
        intro_text=intro,
        image_url=image_url,
        links=links,
    )


# ---------------------------------------------------------------------------
# Claude (next-hop selection + type classification)
# ---------------------------------------------------------------------------

claude = Anthropic(api_key=ANTHROPIC_API_KEY)


def _shortlist_links(links: list[str], visited: set[str], forbidden: set[str], limit: int = 80) -> list[str]:
    """Filter Wikipedia links to a manageable set before sending to Claude."""
    import re
    date_re = re.compile(r"^\d{4}s?$|^\d{1,2} \w+$|^\w+ \d{4}$|^List of |^Index of |^Outline of ")
    skip = visited | forbidden
    filtered = [
        t for t in links
        if t not in skip and not date_re.match(t) and len(t) > 2
    ]
    return filtered[:limit]


def pick_next_hop(
    current: WikiPage,
    target_title: str,
    visited: list[str],
    forbidden: set[str],
) -> str:
    """
    Ask Claude to pick the next page title from `current.links`.

    Bias: plausible step toward `target_title`, but favor non-obvious connections.
    `forbidden` is the set of intermediate titles used by other permutations of
    the same start/end — we want diverse paths.

    Returns: a title from `current.links`.
    """
    candidates = _shortlist_links(current.links, set(visited), forbidden)
    if not candidates:
        candidates = [t for t in current.links if t not in set(visited) | forbidden]
    if not candidates:
        raise ValueError(f"No valid candidates from {current.title!r}")

    def _ask(candidate_list: list[str]) -> str:
        prompt = f"""You are walking the Wikipedia link graph from "{current.title}" toward "{target_title}".

You've already visited: {visited}
Avoid (used by other permutations): {sorted(forbidden)}

From the current page "{current.title}", here are the available internal links:
{json.dumps(candidate_list)}

Pick exactly ONE link that:
- moves meaningfully closer to "{target_title}",
- prefers a non-obvious but plausible connection over the most predictable one,
- is not in the visited or avoid lists.

Reply with ONLY the chosen title, exactly as it appears in the list above. No quotes, no explanation."""
        msg = claude.messages.create(
            model=CLAUDE_MODEL,
            max_tokens=200,
            messages=[{"role": "user", "content": prompt}],
        )
        return msg.content[0].text.strip()

    choice = _ask(candidates)
    if choice not in candidates:
        # Retry once with the full unfiltered list (minus visited/forbidden)
        full_candidates = [t for t in current.links if t not in set(visited) | forbidden]
        choice = _ask(full_candidates)
        if choice not in full_candidates:
            # Fall back to first candidate
            choice = candidates[0]
    return choice


def classify_node_type(page: WikiPage) -> str:
    """
    Classify a Wikipedia page as one of NODE_TYPES based on its intro paragraph.
    Returns one of: 'place', 'idea', 'person', 'event', 'thing'.
    """
    prompt = f"""Classify this Wikipedia article as exactly one of: place, idea, person, event, thing.

Title: {page.title}
Intro: {page.intro_text[:1500]}

Reply with ONLY the single word."""
    msg = claude.messages.create(
        model=CLAUDE_MODEL,
        max_tokens=10,
        messages=[{"role": "user", "content": prompt}],
    )
    out = msg.content[0].text.strip().lower()
    return out if out in NODE_TYPES else "thing"


def summarize_theme(path_titles: list[str]) -> str:
    """One-line label for a completed path, e.g. 'via wildlife management'. ~6 words."""
    prompt = f"""Given this Wikipedia rabbit-hole path:
{" → ".join(path_titles)}

In 6 words or fewer, summarize what THEME connects the start to the end. Examples:
- "via American transcendentalism"
- "through colonial maritime trade"
- "by way of ecological restoration"

Reply with ONLY the phrase, no quotes."""
    msg = claude.messages.create(
        model=CLAUDE_MODEL,
        max_tokens=40,
        messages=[{"role": "user", "content": prompt}],
    )
    return msg.content[0].text.strip()


# ---------------------------------------------------------------------------
# Supabase persistence
# ---------------------------------------------------------------------------

sb: Client = create_client(
    SUPABASE_URL,
    SUPABASE_SERVICE_ROLE_KEY,
    options=ClientOptions(schema=DB_SCHEMA),
)


def upsert_node(
    page: WikiPage,
    node_type: Optional[str] = None,
    located_in_id: Optional[int] = None,
) -> int:
    """
    Upsert a node by wikipedia_url. Returns the node id.

    If node_type is None and the row is new, classify_node_type() before insert.
    If the row already exists and located_in_id is provided, backfill it if missing.
    """
    result = sb.table("nodes").select("id,located_in").eq("wikipedia_url", page.url).execute()
    if result.data:
        existing = result.data[0]
        if located_in_id and not existing.get("located_in"):
            sb.table("nodes").update({"located_in": located_in_id}).eq("id", existing["id"]).execute()
        return existing["id"]

    if node_type is None:
        node_type = classify_node_type(page)

    row = {
        "wikipedia_url": page.url,
        "title": page.title,
        "node_type": node_type,
        "intro_text": (page.intro_text or "")[:4000] or None,
        "image_url": page.image_url,
        "located_in": located_in_id,
    }
    insert_result = sb.table("nodes").upsert(row, on_conflict="wikipedia_url").execute()
    return insert_result.data[0]["id"]


def resolve_located_in(title_or_url: str) -> int:
    """Get or create a node for a location (e.g. 'Monhegan Island'). Returns its id."""
    page = fetch_wiki_page(title_or_url)
    return upsert_node(page)


def insert_path(start_node_id: int, end_node_id: int, hops: list[int], theme: str, completed: bool, group: str) -> int:
    """
    Insert a path row and its edges.

    `hops` is the ordered list of node ids from start to end inclusive.
    Convention: `paths.total_hops` is the number of EDGES, so total_hops = len(hops) - 1.
    Edges are derived from consecutive pairs in `hops` (zero-indexed `position_in_path`).
    """
    path_result = sb.table("paths").insert({
        "start_node_id": start_node_id,
        "end_node_id": end_node_id,
        "total_hops": len(hops) - 1,
        "theme": theme or None,
        "completed": completed,
        "permutation_group": group,
    }).execute()
    path_id = path_result.data[0]["id"]

    edges = [
        {
            "path_id": path_id,
            "from_node_id": hops[i],
            "to_node_id": hops[i + 1],
            "position_in_path": i,
        }
        for i in range(len(hops) - 1)
    ]
    if edges:
        sb.table("edges").insert(edges).execute()

    return path_id


# ---------------------------------------------------------------------------
# Main loop
# ---------------------------------------------------------------------------

def find_path(start: str, end: str, forbidden: set[str], max_hops: int = MAX_HOPS) -> Path:
    """
    Walk from `start` to `end` one hop at a time, up to max_hops.
    `forbidden` is intermediate titles to avoid (for diversity across permutations).
    Returns a Path; `completed` indicates whether we reached `end` within the cap.
    """
    start = normalize_title(start)
    end = normalize_title(end)
    visited: list[str] = [start]
    current = fetch_wiki_page(start)

    for hop in range(max_hops):
        # If the target is one click away, take it.
        if end in current.links:
            visited.append(end)
            return Path(start_title=start, end_title=end, hops=visited, completed=True)

        next_title = pick_next_hop(
            current=current,
            target_title=end,
            visited=visited,
            forbidden=forbidden,
        )

        # If Claude picked the end directly, we're done — don't re-fetch.
        if next_title == end:
            visited.append(end)
            return Path(start_title=start, end_title=end, hops=visited, completed=True)

        visited.append(next_title)
        current = fetch_wiki_page(next_title)

    return Path(start_title=start, end_title=end, hops=visited, completed=False)


def run_scenario(
    start: str,
    place: str,
    permutations: int = DEFAULT_PERMUTATIONS,
    max_hops: int = MAX_HOPS,
) -> list[Path]:
    """
    Produce `permutations` distinct paths from start → place.

    `place` is both the end of the path and the located_in value for the start node.
    Every path in Field Trips connects an object to the place it belongs to.
    """
    forbidden: set[str] = set()
    results: list[Path] = []
    group = f"{normalize_title(start)}__{normalize_title(place)}"

    print(f"  Resolving place: {place!r} …")
    located_in_id = resolve_located_in(place)

    for i in range(permutations):
        path = find_path(start, place, forbidden=forbidden, max_hops=max_hops)
        if path.completed:
            forbidden.update(path.hops[1:-1])
            path.theme = summarize_theme(path.hops)
        results.append(path)

        node_ids: list[int] = []
        for idx, title in enumerate(path.hops):
            page = fetch_wiki_page(title)
            if idx == 0:
                nid = upsert_node(page, located_in_id=located_in_id)
            else:
                nid = upsert_node(page)
            node_ids.append(nid)

        insert_path(node_ids[0], node_ids[-1], node_ids, path.theme or "", path.completed, group)

    return results


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

@click.group()
def cli():
    """Field Trips path-finder."""


@cli.command()
@click.option("--start", required=True, help="Wikipedia page title or URL (the object).")
@click.option("--place", required=True, help="Wikipedia page title or URL of the place it belongs to (also the path end).")
@click.option("--permutations", default=DEFAULT_PERMUTATIONS, type=int)
@click.option("--max-hops", default=MAX_HOPS, type=int)
def one(start: str, place: str, permutations: int, max_hops: int):
    """Find paths from an object to the place it belongs to."""
    paths = run_scenario(start, place, permutations=permutations, max_hops=max_hops)
    for i, p in enumerate(paths, 1):
        status = "✓" if p.completed else "× (hop cap)"
        print(f"\n[{i}] {status}  {p.theme or ''}")
        print("    " + " → ".join(p.hops))


@cli.command()
@click.option("--scenarios", "scenarios_path", default="scenarios.yaml", type=click.Path(exists=True))
def run(scenarios_path: str):
    """Run every scenario in a YAML file."""
    with open(scenarios_path) as f:
        cfg = yaml.safe_load(f)
    defaults = cfg.get("defaults", {})
    for s in cfg.get("scenarios", []):
        run_scenario(
            start=s["start"],
            end=s["end"],
            permutations=s.get("permutations", defaults.get("permutations", DEFAULT_PERMUTATIONS)),
            max_hops=s.get("max_hops", defaults.get("max_hops", MAX_HOPS)),
        )


if __name__ == "__main__":
    cli()
