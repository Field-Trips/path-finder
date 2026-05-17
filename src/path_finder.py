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

MAX_HOPS = int(os.environ.get("MAX_HOPS", "15"))
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
    narrative: Optional[str] = None
    representative_node_id: Optional[int] = None
    representative_title: Optional[str] = None
    representative_type: Optional[str] = None
    representative_image: Optional[str] = None


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


def claude_create(**kwargs):
    """
    Wrapper around claude.messages.create() with retry on rate-limit errors.

    On HTTP 429 (Anthropic rate limit), wait with exponential backoff and retry
    up to 6 times. Other errors propagate. Adds small random jitter so multiple
    parallel processes don't all wake up and re-collide on the limit.
    """
    import time
    import random
    from anthropic import RateLimitError, APIConnectionError, APIStatusError

    last_err: Exception = RuntimeError("unreachable")
    for attempt in range(6):
        try:
            return claude.messages.create(**kwargs)
        except RateLimitError as e:
            last_err = e
            wait = min(30 * (2 ** attempt), 240) + random.uniform(0, 5)
            print(f"  ⏳ Rate limit hit — waiting {wait:.0f}s before retry ({attempt + 1}/6)…", flush=True)
            time.sleep(wait)
        except (APIConnectionError, APIStatusError) as e:
            # Transient API/network — short backoff, fewer retries
            last_err = e
            if attempt >= 3:
                raise
            wait = 5 * (2 ** attempt) + random.uniform(0, 2)
            print(f"  ⏳ Anthropic API issue — waiting {wait:.0f}s before retry ({attempt + 1}/4)…", flush=True)
            time.sleep(wait)
    raise last_err


def _stems(title: str) -> tuple[str, str]:
    """
    Returns (first-2-words, last-2-words) of a title, lowercased.
    If the first word is a 4-digit year (e.g. '1933 Nobel Prize in Literature'),
    that year is stripped before computing the prefix — so titles that differ
    ONLY by year still get treated as the same structural pattern.
    """
    words = title.lower().split()
    if words and len(words[0]) == 4 and words[0].isdigit():
        words = words[1:]
    if len(words) < 2:
        s = " ".join(words)
        return (s, s)
    return (" ".join(words[:2]), " ".join(words[-2:]))


def _shortlist_links(links: list[str], visited: set[str], forbidden: set[str], limit: int = 80) -> list[str]:
    """Filter Wikipedia links to a manageable set before sending to Claude."""
    import re
    date_re = re.compile(r"^\d{4}s?$|^\d{1,2} \w+$|^\w+ \d{4}$|^List of |^Index of |^Outline of ")
    skip = visited | forbidden

    # Build prefix + suffix sets from visited titles. Candidates that share
    # either prefix or suffix with a visited title are structurally similar
    # (e.g. "Anarchism in X" prefix, "[year] Nobel Prize in Literature" suffix)
    # and unlikely to make real progress — skip them.
    visited_prefixes: set[str] = set()
    visited_suffixes: set[str] = set()
    for t in visited:
        p, s = _stems(t)
        if len(p.split()) >= 2:
            visited_prefixes.add(p)
        if len(s.split()) >= 2:
            visited_suffixes.add(s)

    filtered = []
    for t in links:
        if t in skip or date_re.match(t) or len(t) <= 2:
            continue
        p, s = _stems(t)
        if p in visited_prefixes or s in visited_suffixes:
            continue
        filtered.append(t)
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
        msg = claude_create(
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
    msg = claude_create(
        model=CLAUDE_MODEL,
        max_tokens=10,
        messages=[{"role": "user", "content": prompt}],
    )
    out = msg.content[0].text.strip().lower()
    return out if out in NODE_TYPES else "thing"


def summarize_theme(path_titles: list[str]) -> tuple[str, str]:
    """
    Returns (theme, narrative) for a completed path.

    `theme` — a short 6–12 word phrase tagging the connection (for compact display).
    `narrative` — a 2–3 paragraph explanation in the voice of James Burke or
                  Adam Curtis: names specific mechanisms, people, technologies,
                  or ideologies. Concrete, not abstract.
    """
    path_str = " → ".join(path_titles)

    # Single Claude call for both, returned as JSON so we can split them cleanly.
    prompt = f"""You are connecting the dots between Wikipedia articles in the voice of James Burke (Connections) and Adam Curtis. Their gift: naming the SPECIFIC mechanism — a technology, a financial instrument, a translator, a friendship, an ideology that mutated — that actually links two seemingly distant things. They favour the concrete over the abstract, the surprising-but-rigorous over the obvious.

Here is a path of Wikipedia articles, start to end:

{path_str}

Produce TWO things:

1. A short "theme" — 6 to 12 words, like a chapter title. Name the connecting mechanism, not a topic. Examples of the voice:
   - "via the financial instruments that funded the war"
   - "tracing how mysticism shaped political dissent in pre-revolutionary Russia"
   - "through the technologies of mass production that art tried to resist"
   - "by the artists who would later sell out"

2. A "narrative" — 2 to 3 short paragraphs, ~120-220 words total. Tell the story of how the start actually leads to the end through this specific route. Use specifics: name the people, the dates, the inventions, the ideas. Make at least one observation that is not obvious — a hidden chain or unintended consequence. End the narrative on a note that lands; do not trail off.

Write in plain, unornamented prose. No "fascinating," no "intriguing," no rhetorical questions. Past tense.

Reply with ONLY this JSON, no preamble, no markdown fences:
{{"theme": "...", "narrative": "..."}}"""

    msg = claude_create(
        model=CLAUDE_MODEL,
        max_tokens=600,
        messages=[{"role": "user", "content": prompt}],
    )
    raw = msg.content[0].text.strip()

    # Strip markdown fences if Claude included them despite instructions.
    if raw.startswith("```"):
        raw = raw.strip("`").lstrip("json").strip()

    try:
        data = json.loads(raw)
        theme = (data.get("theme") or "").strip()
        narrative = (data.get("narrative") or "").strip()
        return theme, narrative
    except Exception:
        # Fallback: return the raw text as both, so we lose nothing.
        return raw[:80], raw


# ---------------------------------------------------------------------------
# Supabase persistence
# ---------------------------------------------------------------------------

sb: Client = create_client(
    SUPABASE_URL,
    SUPABASE_SERVICE_ROLE_KEY,
    options=ClientOptions(schema=DB_SCHEMA),
)


def upsert_node(page: WikiPage, node_type: Optional[str] = None) -> int:
    """
    Upsert a node by wikipedia_url. Returns the node id.

    If node_type is None and the row is new, classify_node_type() before insert.
    """
    result = sb.table("nodes").select("id").eq("wikipedia_url", page.url).execute()
    if result.data:
        return result.data[0]["id"]

    if node_type is None:
        node_type = classify_node_type(page)

    row = {
        "wikipedia_url": page.url,
        "title": page.title,
        "node_type": node_type,
        "intro_text": (page.intro_text or "")[:4000] or None,
        "image_url": page.image_url,
    }
    insert_result = sb.table("nodes").upsert(row, on_conflict="wikipedia_url").execute()
    return insert_result.data[0]["id"]


def resolve_node(title_or_url: str) -> tuple[int, WikiPage]:
    """Fetch a Wikipedia page, upsert its node, return (node_id, page)."""
    page = fetch_wiki_page(title_or_url)
    return upsert_node(page), page


# ---------------------------------------------------------------------------
# Anchors
# ---------------------------------------------------------------------------

def add_anchor(
    anchor_title_or_url: str,
    place_title_or_url: str,
    rationale: Optional[str] = None,
    custom_image_url: Optional[str] = None,
) -> dict:
    """
    Create or update an anchor. Returns the anchor row.

    An anchor is a curated person/place/thing pinned on the map of a place.
    """
    anchor_id_node, anchor_page = resolve_node(anchor_title_or_url)
    place_id_node, place_page = resolve_node(place_title_or_url)

    # Upsert by (node_id, place_node_id)
    existing = (
        sb.table("anchors")
        .select("*")
        .eq("node_id", anchor_id_node)
        .eq("place_node_id", place_id_node)
        .execute()
    )
    if existing.data:
        updates = {}
        if rationale is not None:
            updates["rationale"] = rationale
        if custom_image_url is not None:
            updates["custom_image_url"] = custom_image_url
        if updates:
            result = sb.table("anchors").update(updates).eq("id", existing.data[0]["id"]).execute()
            return result.data[0]
        return existing.data[0]

    row = {
        "node_id": anchor_id_node,
        "place_node_id": place_id_node,
        "rationale": rationale,
        "custom_image_url": custom_image_url,
    }
    result = sb.table("anchors").insert(row).execute()
    return result.data[0]


def list_anchors(place_title_or_url: Optional[str] = None) -> list[dict]:
    """List anchors. If place is provided, filter to that place."""
    query = sb.table("anchors").select(
        "id,rationale,custom_image_url,created_at,"
        "node:nodes!anchors_node_id_fkey(id,title,wikipedia_url,node_type,image_url),"
        "place:nodes!anchors_place_node_id_fkey(id,title,wikipedia_url)"
    )
    if place_title_or_url:
        place_page = fetch_wiki_page(place_title_or_url)
        place_row = sb.table("nodes").select("id").eq("wikipedia_url", place_page.url).execute()
        if not place_row.data:
            return []
        query = query.eq("place_node_id", place_row.data[0]["id"])
    return query.order("id").execute().data


def delete_anchor(anchor_id: int) -> None:
    """Delete an anchor by id."""
    sb.table("anchors").delete().eq("id", anchor_id).execute()


# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

def insert_path(
    place_node_id: int,
    concept_node_id: int,
    hops: list[int],
    theme: str,
    completed: bool,
    group: str,
    anchor_id: Optional[int] = None,
    narrative: Optional[str] = None,
) -> int:
    """
    Insert a path row and its edges.

    `hops` is the ordered list of node ids: [place, ..., anchor, ..., concept].
    `total_hops` = number of edges = len(hops) - 1.
    """
    path_result = sb.table("paths").insert({
        "place_node_id": place_node_id,
        "concept_node_id": concept_node_id,
        "total_hops": len(hops) - 1,
        "theme": theme or None,
        "narrative": narrative or None,
        "completed": completed,
        "permutation_group": group,
        "anchor_id": anchor_id,
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
        try:
            current = fetch_wiki_page(next_title)
        except (ValueError, DisambiguationError):
            # Claude picked a title that doesn't exist or is a disambiguation page.
            # Skip it and try again from the same position next hop.
            visited.pop()
            forbidden.add(next_title)

    return Path(start_title=start, end_title=end, hops=visited, completed=False)


STAGE1_HOPS = 4   # Place → Anchor (tight, anchors are close to their place)
STAGE2_HOPS = 15  # Anchor → Concept (the broader journey)


def run_scenario(
    place: str,
    anchor: str,
    concept: str,
    permutations: int = DEFAULT_PERMUTATIONS,
    stage1_hops: int = STAGE1_HOPS,
    stage2_hops: int = STAGE2_HOPS,
    allow_duplicates: bool = False,
) -> list[Path]:
    """
    Produce `permutations` distinct paths from Place → Anchor → Concept.

    Two-stage pathfinding:
      Stage 1: Place → Anchor  (tight, default 4 hops)
      Stage 2: Anchor → Concept (broad, default 15 hops)

    Skips with a warning if a path from this anchor to this concept already
    exists in the database, unless allow_duplicates=True.
    """
    forbidden: set[str] = set()
    results: list[Path] = []
    group = f"{normalize_title(place)}__{normalize_title(anchor)}__{normalize_title(concept)}"

    print(f"  Resolving place:   {place!r} …")
    place_node_id, place_page = resolve_node(place)
    print(f"  Resolving anchor:  {anchor!r} …")
    anchor_node_id, anchor_page = resolve_node(anchor)
    print(f"  Resolving concept: {concept!r} …")
    concept_node_id, concept_page = resolve_node(concept)

    # Ensure anchor row exists (auto-create if needed).
    anchor_row = add_anchor(anchor_page.url, place_page.url)
    anchor_id = anchor_row["id"]

    # Duplicate check — only skip if there's at least one COMPLETED path.
    # Incomplete paths (hit hop cap) are fair game to retry.
    if not allow_duplicates:
        existing = sb.table("paths").select("id,total_hops,completed").eq("anchor_id", anchor_id).eq("concept_node_id", concept_node_id).execute()
        completed_existing = [p for p in existing.data if p.get("completed")]
        if completed_existing:
            ids = ", ".join(f"#{p['id']}" for p in completed_existing)
            print(f"\n  ⚠  Skipping: {len(completed_existing)} completed path(s) already connect")
            print(f"     {anchor_page.title} → {concept_page.title}  ({ids})")
            print(f"     Pass --allow-duplicates to run anyway.\n")
            return []

    for i in range(permutations):
        print(f"\n  → Permutation {i + 1}/{permutations}")
        print(f"    Stage 1: {place_page.title} → {anchor_page.title}")
        stage1 = find_path(place_page.title, anchor_page.title, forbidden=forbidden, max_hops=stage1_hops)

        print(f"    Stage 2: {anchor_page.title} → {concept_page.title}")
        stage2 = find_path(anchor_page.title, concept_page.title, forbidden=forbidden, max_hops=stage2_hops)

        # Combine: stage1 hops + stage2 hops (drop duplicate anchor at the join)
        combined_hops = stage1.hops + stage2.hops[1:]
        completed = stage1.completed and stage2.completed

        path = Path(
            start_title=place_page.title,
            end_title=concept_page.title,
            hops=combined_hops,
            completed=completed,
        )
        if completed:
            forbidden.update(combined_hops[1:-1])
            theme, narrative = summarize_theme(combined_hops)
            path.theme = theme
            path.narrative = narrative
        results.append(path)

        # Persist nodes
        node_ids: list[int] = []
        for title in combined_hops:
            page = fetch_wiki_page(title)
            node_ids.append(upsert_node(page))

        # Always record the user's INTENDED destination, not where the search
        # ended up. Failed (hop-capped) paths previously stored the last-visited
        # node as concept_node_id, which made retry lookups miss them entirely.
        insert_path(
            place_node_id=place_node_id,
            concept_node_id=concept_node_id,
            hops=node_ids,
            theme=path.theme or "",
            narrative=path.narrative,
            completed=path.completed,
            group=group,
            anchor_id=anchor_id,
        )

    return results


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

@click.group()
def cli():
    """Field Trips path-finder."""


@cli.command()
@click.option("--place",   required=True, help="Wikipedia title or URL of the Place (e.g. 'Monhegan Island').")
@click.option("--anchor",  required=True, help="Wikipedia title or URL of the Anchor (the person/place/thing pinned on the map).")
@click.option("--concept", required=True, help="Wikipedia title or URL of the Concept (the destination idea/event).")
@click.option("--permutations", default=DEFAULT_PERMUTATIONS, type=int)
@click.option("--stage1-hops", default=STAGE1_HOPS, type=int, help="Max hops for Place → Anchor.")
@click.option("--stage2-hops", default=STAGE2_HOPS, type=int, help="Max hops for Anchor → Concept.")
@click.option("--allow-duplicates", is_flag=True, default=False, help="Run even if a path from this anchor to this concept already exists.")
def one(place: str, anchor: str, concept: str, permutations: int, stage1_hops: int, stage2_hops: int, allow_duplicates: bool):
    """Find paths: Place → Anchor → Concept."""
    paths = run_scenario(
        place=place, anchor=anchor, concept=concept,
        permutations=permutations,
        stage1_hops=stage1_hops, stage2_hops=stage2_hops,
        allow_duplicates=allow_duplicates,
    )
    for i, p in enumerate(paths, 1):
        status = "✓" if p.completed else "× (hop cap)"
        print(f"\n[{i}] {status}  {p.theme or ''}")
        print("    " + " → ".join(p.hops))
        if p.narrative:
            print()
            # Indent narrative lines so it reads as a block
            for line in p.narrative.split("\n"):
                print(f"    {line}")


@cli.group()
def anchor():
    """Manage anchors (curated objects pinned to a place)."""


@anchor.command("add")
@click.option("--place",     required=True, help="Wikipedia title or URL of the place.")
@click.option("--anchor",    "anchor_url", required=True, help="Wikipedia title or URL of the anchor.")
@click.option("--rationale", default=None, help="Optional: why this anchor belongs to this place.")
@click.option("--image",     default=None, help="Optional: custom image URL.")
def anchor_add(place: str, anchor_url: str, rationale: Optional[str], image: Optional[str]):
    """Add (or update) an anchor."""
    row = add_anchor(anchor_url, place, rationale=rationale, custom_image_url=image)
    print(f"✓ Anchor #{row['id']} saved.")


@anchor.command("list")
@click.option("--place", default=None, help="Filter to a specific place (Wikipedia title or URL).")
@click.option("--json", "json_output", is_flag=True, default=False, help="Output as JSON (for widgets/scripts).")
def anchor_list(place: Optional[str], json_output: bool):
    """List all anchors (optionally filtered by place)."""
    rows = list_anchors(place)
    if json_output:
        slim = [
            {
                "id": r["id"],
                "title": (r.get("node") or {}).get("title"),
                "wikipedia_url": (r.get("node") or {}).get("wikipedia_url"),
                "node_type": (r.get("node") or {}).get("node_type"),
                "place_title": (r.get("place") or {}).get("title"),
                "place_wikipedia_url": (r.get("place") or {}).get("wikipedia_url"),
                "rationale": r.get("rationale"),
            }
            for r in rows
        ]
        print(json.dumps(slim))
        return
    if not rows:
        print("No anchors yet.")
        return
    for r in rows:
        node = r.get("node") or {}
        place_node = r.get("place") or {}
        rationale = (r.get("rationale") or "").strip()
        line = f"  [{r['id']}] {node.get('title')}  →  on {place_node.get('title')}"
        if rationale:
            line += f"\n        “{rationale[:120]}{'…' if len(rationale) > 120 else ''}”"
        print(line)


@anchor.command("remove")
@click.option("--id", "anchor_id", required=True, type=int, help="Anchor id to delete.")
def anchor_remove(anchor_id: int):
    """Delete an anchor by id."""
    delete_anchor(anchor_id)
    print(f"✓ Anchor #{anchor_id} removed.")


@cli.command("batch")
@click.option("--place",   required=True, help="Wikipedia title or URL of the Place.")
@click.option("--anchor",  required=True, help="Wikipedia title or URL of the Anchor.")
@click.option("--concepts", required=True, help="Comma-separated list of concept titles/URLs (cap at 5).")
@click.option("--permutations", default=1, type=int)
@click.option("--allow-duplicates", is_flag=True, default=False, help="Run even if a path already exists for a given concept.")
def batch_cmd(place: str, anchor: str, concepts: str, permutations: int, allow_duplicates: bool):
    """Run several concepts in parallel from one anchor. Cap at 5 to stay under rate limits."""
    import subprocess
    import threading
    items = [c.strip() for c in concepts.split(",") if c.strip()]
    if len(items) > 5:
        print(f"⚠  {len(items)} concepts — capping at 5 to stay under rate limits.")
        items = items[:5]
    print(f"\nRunning {len(items)} paths in parallel from {anchor}:\n")
    for c in items:
        print(f"  • {c}")
    print()

    processes = []
    logs: dict[str, str] = {}

    def _run(concept: str):
        cmd = [sys.executable, "-m", "src.path_finder", "one",
               "--place", place, "--anchor", anchor, "--concept", concept,
               "--permutations", str(permutations)]
        if allow_duplicates:
            cmd.append("--allow-duplicates")
        proc = subprocess.run(cmd, capture_output=True, text=True)
        logs[concept] = (proc.stdout or "") + (proc.stderr or "")

    import sys
    threads = [threading.Thread(target=_run, args=(c,)) for c in items]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    for c in items:
        print(f"\n─── {c} ──────────────────────────────────────")
        print(logs.get(c, "(no output)"))


@cli.command("places")
@click.option("--json", "json_output", is_flag=True, default=False)
def places_cmd(json_output: bool):
    """List distinct places that have at least one anchor."""
    rows = sb.table("anchors").select(
        "place:nodes!anchors_place_node_id_fkey(id,title,wikipedia_url)"
    ).execute().data
    seen = set()
    unique = []
    for a in rows:
        p = a.get("place") or {}
        if p.get("id") and p["id"] not in seen:
            seen.add(p["id"])
            unique.append(p)
    if json_output:
        print(json.dumps(unique))
        return
    if not unique:
        print("No places with anchors yet.")
        return
    for p in unique:
        print(f"  [{p['id']}] {p['title']}")


if __name__ == "__main__":
    cli()
