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
    that year is stripped before computing the prefix.
    """
    words = title.lower().split()
    if words and len(words[0]) == 4 and words[0].isdigit():
        words = words[1:]
    if len(words) < 2:
        s = " ".join(words)
        return (s, s)
    return (" ".join(words[:2]), " ".join(words[-2:]))


def _key_word(title: str) -> str:
    """The last word of a title, lowercased and lightly singularized.
    Used to detect 'category clusters' (e.g. multiple titles ending in 'shooting',
    'killings', 'murders', 'attacks')."""
    words = title.lower().split()
    if not words:
        return ""
    w = words[-1].strip(".,!?;:'\"")
    # crude singularization — handles 'shootings'→'shooting', 'attacks'→'attack'
    if w.endswith("ies") and len(w) > 4:
        w = w[:-3] + "y"
    elif w.endswith("s") and len(w) > 3 and not w.endswith("ss"):
        w = w[:-1]
    return w


def _shortlist_links(links: list[str], visited: set[str], forbidden: set[str], limit: int = 80) -> list[str]:
    """Filter Wikipedia links to a manageable set before sending to Claude."""
    import re
    from collections import Counter
    date_re = re.compile(r"^\d{4}s?$|^\d{1,2} \w+$|^\w+ \d{4}$|^List of |^Index of |^Outline of ")
    skip = visited | forbidden

    # Prefix/suffix sets (catch "Anarchism in X" or "[year] Nobel Prize in Literature").
    visited_prefixes: set[str] = set()
    visited_suffixes: set[str] = set()
    for t in visited:
        p, s = _stems(t)
        if len(p.split()) >= 2:
            visited_prefixes.add(p)
        if len(s.split()) >= 2:
            visited_suffixes.add(s)

    # Overused trailing-word check (catches "[year] X shooting"/"X killings"/etc.
    # category clusters where each title differs but the last word repeats).
    last_word_counts: Counter = Counter()
    for t in visited:
        kw = _key_word(t)
        if kw:
            last_word_counts[kw] += 1
    overused_words = {w for w, n in last_word_counts.items() if n >= 2}

    filtered = []
    for t in links:
        if t in skip or date_re.match(t) or len(t) <= 2:
            continue
        p, s = _stems(t)
        if p in visited_prefixes or s in visited_suffixes:
            continue
        if _key_word(t) in overused_words:
            continue
        filtered.append(t)
    return filtered[:limit]


def pick_next_hop(
    current: WikiPage,
    target_title: str,
    visited: list[str],
    forbidden: set[str],
    prefer_direct: bool = False,
    place_context: Optional[str] = None,
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

    bias = (
        "- takes the MOST DIRECT plausible route toward the target (this run "
        "is the 'shortest path' attempt — go for the obvious connection),"
        if prefer_direct else
        "- prefers a non-obvious but plausible connection over the most "
        "predictable one (favor surprising links that still get there),"
    )

    place_hint = (
        f"\nNote: both '{current.title}' and '{target_title}' are anchored to "
        f"the same place: '{place_context}'. The natural route between them "
        "likely passes through articles about that shared place. Prefer hops "
        "that go through the place context where plausible."
        if place_context else ""
    )

    def _ask(candidate_list: list[str]) -> str:
        prompt = f"""You are walking the Wikipedia link graph from "{current.title}" toward "{target_title}".
{place_hint}
You've already visited: {visited}
Avoid (used by other permutations): {sorted(forbidden)}

From the current page "{current.title}", here are the available internal links:
{json.dumps(candidate_list)}

Pick exactly ONE link that:
- moves meaningfully closer to "{target_title}",
{bias}
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


def summarize_theme(path_titles: list[str], branch_via: Optional[str] = None) -> tuple[str, str]:
    """
    Returns (theme, narrative) for a completed path.

    `theme` — a short 6–12 word phrase tagging the connection (for compact display).
    `narrative` — a 2–3 paragraph explanation in the voice of James Burke or
                  Adam Curtis: names specific mechanisms, people, technologies,
                  or ideologies. Concrete, not abstract.

    `branch_via` — if set, the path passed through this branch anchor. The
                   narrative should acknowledge the bridge through that object.
    """
    path_str = " → ".join(path_titles)
    branch_note = (
        f"\n\nNote: this is a BRANCHED path. It travels through '{branch_via}' "
        f"as a bridge object — meaning the connection from the start to the end "
        f"is not direct, but goes through this other curated object on the same "
        f"place. The narrative should acknowledge that bridging move."
        if branch_via else ""
    )

    # Single Claude call for both, returned as JSON so we can split them cleanly.
    prompt = f"""You are connecting the dots between Wikipedia articles in the combined voices of JAMES BURKE (Connections) and ADAM CURTIS. Match their voice and their habit of thought.

BURKE traces material and technological chains. He shows how the stirrup made heavy cavalry possible, which required vast estates to maintain knights, which created universities to administer the estates. The voice is plain, the leaps are surprising, the rigor is in the specificity.

CURTIS works in plain declarative sentences and stacks them until they land. His method, drawn from his actual blog posts:

He goes BEHIND a known headline to reveal the hidden back story. "BP is accused of destroying the wildlife and coastline of America, but if you look back into history you find that BP did something even worse to America. They gave the world Ayatollah Khomeini." The punchline lands as a flat fact.

He names specific people as conduits and stacks their biographies. "He set up a motorcycle task force to smash the mafia in America in the 1930s. Then he narrated the radio series Gang Busters. And he ended up helping create and train the Shah's notorious secret police - the SAVAK." Each clause is matter-of-fact. The cumulative effect is damning.

He makes the small detail specific and physical. A "fly-blown hell, a shanty town called Kaghazabad, or Paper City." Executive role-playing games "played in an old country mansion - using staplers." Four eminent archaeologists arriving "together in a 1970s car at Monsieur Fradin's farmhouse - all determined to destroy him (in their pompous archaeological way)."

He ends quietly, on a sentence that lands but does not moralize. "And now the only person who knows the truth has died." "And maybe to the inept and arrogant response to the crisis in America today."

He uses "And what's more" / "But the price was high" to stack consequences.

His other moves:
- Hidden causal chains across long time spans (a 1951 coup → a 1979 revolution).
- Ideologies that betray their origins.
- The bumbling, post-imperial arrogance of institutions doing more damage than their headline crimes.
- Light irony, never sneering — affection for the strange characters even as the system is damned.

Here is a Wikipedia path:

{path_str}{branch_note}

Produce TWO things in JSON:

1. theme — a 6-12 word chapter title naming the connecting MECHANISM (not the topic). Examples:
   - "the oil company that gave the world Ayatollah Khomeini"
   - "by the academics who would later defect"
   - "how mysticism shaped political dissent in pre-revolutionary Russia"
   - "the rational solutions that produced their opposite"

2. narrative — 2-3 short paragraphs (~150-250 words total). Tell the story of how the start actually leads to the end through THIS specific route. Use specifics: name the people, the dates, the institutions. Make at least one observation that is non-obvious — a hidden chain, a stacked biographical detail, an unintended consequence. End on a sentence that lands. Do not trail off.

About the KIND of connection — important:
Not every path is a chain of direct causation. Many are chains of THEMATIC RESONANCE: articles that belong to a single long pattern — a long history of state violence, of artistic experiment, of religious dissent, of technological optimism gone bad, of women whose deaths went uninvestigated. When that's the shape of the path, the connection IS real: the destination is a specific instance of a much longer pattern, and the path articulates that lineage. Frame it that way.

This is one of Curtis's most characteristic moves: take a single event and locate it as the latest entry in a long lineage that runs through institutions, geographies, decades. "Pennington County sits inside a criminal justice apparatus that runs from capital punishment to assassination to the killing of Martin Luther King Jr. to a cascade of American shootings that end, finally, in a Texas prison break." That kind of cumulative framing IS the connection.

NEVER end the narrative with phrases like "nobody connected them to any of this", "unrelated", "no real link", or similar dismissals. The path itself is the connection. Your job is to name what the path is collectively ABOUT and place the destination inside that pattern.

Voice rules:
- Plain past tense. Short declarative sentences. No "fascinating," "intriguing," rhetorical questions, or rhetorical flourish.
- Stack matter-of-fact clauses; let the cumulative effect do the work.
- Concrete over abstract. Specific names, dates, places, small physical details.
- Do not say "this path shows" or "this connection reveals" — just tell the story.
- Light irony is fine; sneering is not.
- End on a sentence that lands. It can be quiet, devastating, or thematic — but never dismissive.

Reply with ONLY JSON, no preamble, no markdown fences:
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
    branch_anchor_id: Optional[int] = None,
) -> int:
    """
    Insert a path row and its edges.

    `hops` is the ordered list of node ids:
      direct:   [place, ..., anchor, ..., concept]
      branched: [place, ..., anchor, ..., branch_anchor, ..., concept]
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
        "branch_anchor_id": branch_anchor_id,
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

def find_path(start: str, end: str, forbidden: set[str], max_hops: int = MAX_HOPS, prefer_direct: bool = False, place_context: Optional[str] = None) -> Path:
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
            prefer_direct=prefer_direct,
            place_context=place_context,
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
        # First permutation goes for the most direct route. The rest are
        # told to prefer non-obvious connections, for diversity.
        prefer_direct = (i == 0)
        bias_label = "direct" if prefer_direct else "non-obvious"

        print(f"\n  → Permutation {i + 1}/{permutations}  ({bias_label})")
        print(f"    Stage 1: {place_page.title} → {anchor_page.title}")
        stage1 = find_path(place_page.title, anchor_page.title, forbidden=forbidden, max_hops=stage1_hops, prefer_direct=prefer_direct)

        print(f"    Stage 2: {anchor_page.title} → {concept_page.title}")
        stage2 = find_path(anchor_page.title, concept_page.title, forbidden=forbidden, max_hops=stage2_hops, prefer_direct=prefer_direct)

        combined_hops = stage1.hops + stage2.hops[1:]
        completed = stage1.completed and stage2.completed

        path = Path(
            start_title=place_page.title,
            end_title=concept_page.title,
            hops=combined_hops,
            completed=completed,
        )
        results.append(path)

        if not completed:
            # ARCHITECTURE: never save incomplete paths. The DB only holds
            # real completed connections. Retries are treated as fresh attempts.
            print(f"    {' ' * 0}↳ Hit hop cap. Not saved to DB.")
            continue

        forbidden.update(combined_hops[1:-1])
        theme, narrative = summarize_theme(combined_hops)
        path.theme = theme
        path.narrative = narrative

        # Persist nodes only for completed paths
        node_ids: list[int] = []
        for title in combined_hops:
            page = fetch_wiki_page(title)
            node_ids.append(upsert_node(page))

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


def run_branched_scenario(
    place: str,
    anchor: str,
    branch_anchor: str,
    concept: str,
    permutations: int = 1,
    bridge_hops: int = 8,
    stage2_hops: int = STAGE2_HOPS,
    allow_duplicates: bool = False,
) -> list[Path]:
    """
    Branched pathfinding: Place → Anchor → BranchAnchor → Concept.

    Stage 1: Place → Anchor (4 hops, existing logic)
    Stage A: Anchor → BranchAnchor (place-informed, default 8 hops)
    Stage B: BranchAnchor → Concept (fresh pathfinding, default 15 hops)

    Both anchors are assumed to be on the same place.
    """
    forbidden: set[str] = set()
    results: list[Path] = []
    group = f"{normalize_title(place)}__{normalize_title(anchor)}__via_{normalize_title(branch_anchor)}__{normalize_title(concept)}"

    print(f"  Resolving place:         {place!r} …")
    place_node_id, place_page = resolve_node(place)
    print(f"  Resolving anchor:        {anchor!r} …")
    anchor_node_id, anchor_page = resolve_node(anchor)
    print(f"  Resolving branch anchor: {branch_anchor!r} …")
    branch_node_id, branch_page = resolve_node(branch_anchor)
    print(f"  Resolving concept:       {concept!r} …")
    concept_node_id, concept_page = resolve_node(concept)

    # Ensure both anchor rows exist on this place
    anchor_row = add_anchor(anchor_page.url, place_page.url)
    branch_row = add_anchor(branch_page.url, place_page.url)
    anchor_id = anchor_row["id"]
    branch_anchor_id = branch_row["id"]

    # Duplicate check — skip if a completed branched path with this exact triple
    # (anchor, branch, concept) already exists.
    if not allow_duplicates:
        existing = (
            sb.table("paths").select("id")
            .eq("anchor_id", anchor_id)
            .eq("branch_anchor_id", branch_anchor_id)
            .eq("concept_node_id", concept_node_id)
            .eq("completed", True)
            .execute()
        )
        if existing.data:
            ids = ", ".join(f"#{p['id']}" for p in existing.data)
            print(f"\n  ⚠  Skipping: branched path already exists via {branch_page.title} ({ids})\n")
            return []

    for i in range(permutations):
        prefer_direct = (i == 0)
        bias_label = "direct" if prefer_direct else "non-obvious"
        print(f"\n  → Permutation {i + 1}/{permutations}  ({bias_label}, branched)")

        print(f"    Stage 1: {place_page.title} → {anchor_page.title}")
        stage1 = find_path(place_page.title, anchor_page.title, forbidden=forbidden, max_hops=STAGE1_HOPS, prefer_direct=prefer_direct)

        print(f"    Stage A: {anchor_page.title} → {branch_page.title}  (via {place_page.title})")
        stage_a = find_path(anchor_page.title, branch_page.title, forbidden=forbidden, max_hops=bridge_hops, prefer_direct=prefer_direct, place_context=place_page.title)

        print(f"    Stage B: {branch_page.title} → {concept_page.title}")
        stage_b = find_path(branch_page.title, concept_page.title, forbidden=forbidden, max_hops=stage2_hops, prefer_direct=prefer_direct)

        combined_hops = stage1.hops + stage_a.hops[1:] + stage_b.hops[1:]
        completed = stage1.completed and stage_a.completed and stage_b.completed

        path = Path(
            start_title=place_page.title,
            end_title=concept_page.title,
            hops=combined_hops,
            completed=completed,
        )
        results.append(path)

        if not completed:
            failing_stage = "1" if not stage1.completed else ("A" if not stage_a.completed else "B")
            print(f"    ↳ Hit hop cap on stage {failing_stage}. Not saved.")
            continue

        forbidden.update(combined_hops[1:-1])
        theme, narrative = summarize_theme(combined_hops, branch_via=branch_page.title)
        path.theme = theme
        path.narrative = narrative

        node_ids: list[int] = []
        for title in combined_hops:
            page = fetch_wiki_page(title)
            node_ids.append(upsert_node(page))

        insert_path(
            place_node_id=place_node_id,
            concept_node_id=concept_node_id,
            hops=node_ids,
            theme=path.theme or "",
            narrative=path.narrative,
            completed=path.completed,
            group=group,
            anchor_id=anchor_id,
            branch_anchor_id=branch_anchor_id,
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
            for line in p.narrative.split("\n"):
                print(f"    {line}")


@cli.command("branched")
@click.option("--place",         required=True, help="Wikipedia title or URL of the Place.")
@click.option("--anchor",        required=True, help="Wikipedia title or URL of the primary Anchor.")
@click.option("--branch-anchor", required=True, help="Wikipedia title or URL of the Branch Anchor (an existing anchor on the same place).")
@click.option("--concept",       required=True, help="Wikipedia title or URL of the Concept.")
@click.option("--permutations",  default=1, type=int)
@click.option("--bridge-hops",   default=8,  type=int, help="Max hops for Anchor → BranchAnchor (place-informed).")
@click.option("--stage2-hops",   default=STAGE2_HOPS, type=int, help="Max hops for BranchAnchor → Concept.")
@click.option("--allow-duplicates", is_flag=True, default=False)
def branched(place: str, anchor: str, branch_anchor: str, concept: str,
             permutations: int, bridge_hops: int, stage2_hops: int, allow_duplicates: bool):
    """Find branched paths: Place → Anchor → BranchAnchor → Concept."""
    paths = run_branched_scenario(
        place=place, anchor=anchor, branch_anchor=branch_anchor, concept=concept,
        permutations=permutations, bridge_hops=bridge_hops, stage2_hops=stage2_hops,
        allow_duplicates=allow_duplicates,
    )
    for i, p in enumerate(paths, 1):
        status = "✓" if p.completed else "× (hop cap)"
        print(f"\n[{i}] {status}  {p.theme or ''}")
        print("    " + " → ".join(p.hops))
        if p.narrative:
            print()
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


@cli.command("concepts")
@click.option("--json", "json_output", is_flag=True, default=False)
def concepts_cmd(json_output: bool):
    """List distinct concepts (destinations) that have at least one completed path."""
    rows = (
        sb.table("paths").select("concept:nodes!paths_concept_node_id_fkey(id,title,wikipedia_url)")
        .eq("completed", True).execute().data
    )
    seen = set()
    unique = []
    for r in rows:
        c = r.get("concept") or {}
        if c.get("id") and c["id"] not in seen:
            seen.add(c["id"])
            unique.append(c)
    unique.sort(key=lambda c: (c.get("title") or "").lower())
    if json_output:
        print(json.dumps(unique))
        return
    if not unique:
        print("No concepts with completed paths yet.")
        return
    for c in unique:
        print(f"  · {c['title']}")


@cli.command("summary")
@click.option("--json", "json_output", is_flag=True, default=False)
def summary_cmd(json_output: bool):
    """Show current state of the collection: places, anchors, concepts, paths."""
    places = sb.table("anchors").select(
        "place:nodes!anchors_place_node_id_fkey(id,title,wikipedia_url)"
    ).execute().data
    place_set: dict[int, dict] = {}
    for a in places:
        p = a.get("place") or {}
        if p.get("id"):
            place_set[p["id"]] = p
    place_list = sorted(place_set.values(), key=lambda p: (p.get("title") or "").lower())

    anchors_raw = sb.table("anchors").select(
        "id,rationale,"
        "node:nodes!anchors_node_id_fkey(id,title,node_type),"
        "place:nodes!anchors_place_node_id_fkey(id,title)"
    ).execute().data
    anchors_by_place: dict[int, list[dict]] = {}
    for a in anchors_raw:
        pid = (a.get("place") or {}).get("id")
        if pid is not None:
            anchors_by_place.setdefault(pid, []).append(a)
    for v in anchors_by_place.values():
        v.sort(key=lambda r: ((r.get("node") or {}).get("title") or "").lower())

    paths = sb.table("paths").select(
        "id,total_hops,branch_anchor_id,"
        "concept:nodes!paths_concept_node_id_fkey(id,title),"
        "anchor:anchors!paths_anchor_id_fkey(id,node:nodes!anchors_node_id_fkey(title))"
    ).eq("completed", True).execute().data

    concepts_set: dict[int, str] = {}
    for p in paths:
        c = p.get("concept") or {}
        if c.get("id"):
            concepts_set[c["id"]] = c.get("title") or "?"
    concept_titles = sorted(concepts_set.values(), key=str.lower)

    # Group paths by (anchor, concept) pair to show counts
    pair_counts: dict[tuple[str, str], int] = {}
    pair_branched: dict[tuple[str, str], int] = {}
    for p in paths:
        anchor_title = ((p.get("anchor") or {}).get("node") or {}).get("title") or "?"
        concept_title = (p.get("concept") or {}).get("title") or "?"
        key = (anchor_title, concept_title)
        pair_counts[key] = pair_counts.get(key, 0) + 1
        if p.get("branch_anchor_id"):
            pair_branched[key] = pair_branched.get(key, 0) + 1
    pair_list = sorted(pair_counts.items(), key=lambda kv: (kv[0][0].lower(), kv[0][1].lower()))

    if json_output:
        print(json.dumps({
            "places": place_list,
            "anchors_by_place": {str(k): v for k, v in anchors_by_place.items()},
            "concepts": concept_titles,
            "paths_total": len(paths),
            "pairs": [{"anchor": a, "concept": c, "count": n, "branched": pair_branched.get((a, c), 0)} for (a, c), n in pair_list],
        }))
        return

    # Plain text rendering
    print()
    print(f"Field Trips — current state")
    print()
    print(f"Places ({len(place_list)}):")
    for p in place_list:
        print(f"  · {p['title']}")
    print()

    total_anchors = sum(len(v) for v in anchors_by_place.values())
    print(f"Anchors ({total_anchors}):")
    for place in place_list:
        rows = anchors_by_place.get(place["id"], [])
        if not rows:
            continue
        print(f"  on {place['title']}:")
        for a in rows:
            node = a.get("node") or {}
            print(f"    · {node.get('title')}  ({node.get('node_type') or '?'})")
    print()

    print(f"Concepts ({len(concept_titles)}):")
    for t in concept_titles:
        print(f"  · {t}")
    print()

    print(f"Paths ({len(paths)} completed across {len(pair_list)} unique anchor → concept pairs):")
    for (a, c), n in pair_list:
        branched = pair_branched.get((a, c), 0)
        suffix = f"  ({n})" if n > 1 else ""
        bsuffix = f"  {n - branched} direct + {branched} branched" if branched else ""
        print(f"  · {a}  →  {c}{suffix}{bsuffix}")
    print()


@cli.command("backfill-narratives")
@click.option("--dry-run", is_flag=True, default=False, help="Show what would be backfilled without making changes.")
@click.option("--limit", default=None, type=int, help="Process at most N paths.")
@click.option("--rewrite", is_flag=True, default=False,
              help="Regenerate themes + narratives even for paths that already have one (use after prompt changes).")
def backfill_narratives_cmd(dry_run: bool, limit: Optional[int], rewrite: bool):
    """
    Generate themes and narratives for completed paths that don't have them yet.

    For each path:
      1. Reconstruct the ordered list of hop titles from the edges table.
      2. Look up the branch anchor title if the path is branched.
      3. Call summarize_theme() — the same function the main flow uses, so
         themes/narratives backfilled here match those generated live.
      4. Write the result back to the paths table.

    Cost: ~$0.005 per path (one Sonnet API call). The rate-limit retry
    wrapper handles 429s automatically.
    """
    query = sb.table("paths").select(
        "id, completed, theme, narrative, anchor_id, branch_anchor_id"
    ).eq("completed", True).order("id")
    if not rewrite:
        query = query.is_("narrative", "null")
    paths = query.execute().data

    if limit is not None:
        paths = paths[:limit]

    if not paths:
        print("✓ Nothing to backfill — every completed path already has a narrative.")
        return

    action = "Regenerating" if rewrite else "Backfilling"
    print(f"\n{action} {len(paths)} path(s).")
    if dry_run:
        for p in paths:
            print(f"  Path #{p['id']}  (would " + ("rewrite" if rewrite else "fill") + ")")
        print("\n(dry run — no changes made)")
        return

    for i, p in enumerate(paths, 1):
        path_id = p["id"]
        print(f"\n[{i}/{len(paths)}] Path #{path_id}")

        # Pull the ordered edges and resolve titles for from + to nodes.
        edges = (
            sb.table("edges")
            .select(
                "position_in_path, from_node_id, to_node_id, "
                "from_node:nodes!edges_from_node_id_fkey(title), "
                "to_node:nodes!edges_to_node_id_fkey(title)"
            )
            .eq("path_id", path_id)
            .order("position_in_path")
            .execute()
            .data
        )
        if not edges:
            print("  ⚠  no edges found, skipping")
            continue

        hop_titles: list[str] = [(edges[0].get("from_node") or {}).get("title") or "?"]
        for e in edges:
            hop_titles.append((e.get("to_node") or {}).get("title") or "?")

        # Trim middle for display
        if len(hop_titles) <= 4:
            preview = " → ".join(hop_titles)
        else:
            preview = f"{hop_titles[0]} → … ({len(hop_titles) - 2} hops) … → {hop_titles[-1]}"
        print(f"  {preview}")

        # Look up branch anchor title if branched
        branch_via: Optional[str] = None
        if p.get("branch_anchor_id"):
            row = (
                sb.table("anchors")
                .select("node:nodes!anchors_node_id_fkey(title)")
                .eq("id", p["branch_anchor_id"])
                .execute()
                .data
            )
            if row:
                branch_via = (row[0].get("node") or {}).get("title")
            if branch_via:
                print(f"  {dim_text('branched via')} {branch_via}")

        try:
            theme, narrative = summarize_theme(hop_titles, branch_via=branch_via)
        except Exception as exc:
            print(f"  ✗ summarize_theme failed: {exc}")
            continue

        sb.table("paths").update({
            "theme": theme,
            "narrative": narrative,
        }).eq("id", path_id).execute()

        print(f"  ✓ {theme}")

    print(f"\nDone. Backfilled {len(paths)} path(s).")


def dim_text(s: str) -> str:
    return f"\033[2m{s}\033[0m"


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
