from __future__ import annotations
import json
import math
import os
import pathlib
import re
import urllib.request

from ddgs import DDGS


def _rules_dir() -> pathlib.Path:
    """Resolve the offline rules library dir without depending on skull.config.

    Mirrors config's convention (OMEGA7_DATA_DIR, else the repo root) so it works
    both here and on older deployments that predate the config data-dir refactor.
    RULES_DIR may be a bare name (resolved under the data dir) or an absolute path."""
    repo_root = pathlib.Path(__file__).resolve().parent.parent
    data_dir = pathlib.Path(os.getenv("OMEGA7_DATA_DIR", "~/.config/omega7")).expanduser()
    rules = pathlib.Path(os.getenv("RULES_DIR", "Rules")).expanduser()
    if rules.is_absolute():
        return rules
    if (repo_root / rules).exists():
        return repo_root / rules
    return data_dir / rules

_WMO_CODES: dict[int, str] = {
    0: "clear sky",
    1: "mainly clear", 2: "partly cloudy", 3: "overcast",
    45: "foggy", 48: "depositing rime fog",
    51: "light drizzle", 53: "moderate drizzle", 55: "dense drizzle",
    61: "light rain", 63: "moderate rain", 65: "heavy rain",
    71: "light snow", 73: "moderate snow", 75: "heavy snow", 77: "snow grains",
    80: "light rain showers", 81: "moderate rain showers", 82: "heavy rain showers",
    85: "light snow showers", 86: "heavy snow showers",
    95: "thunderstorm", 96: "thunderstorm with hail", 99: "thunderstorm with heavy hail",
}

# Keyword → doc page routing. For each entry: (path, [keywords that suggest this page]).
# Used to concept-boost the local Necromunda library: when a query hits a concept
# whose canonical page's title doesn't contain the word (e.g. "On Fire" lives inside
# "Conditions"), the matching page's score is boosted via its URL path.
_NECRO_ROUTES = [
    ("gang-fighters-and-their-weaponry/weapon-traits", [
        "trait", "weapon trait", "paired", "blaze", "rapid fire", "blast", "template",
        "knockback", "rending", "plentiful", "scarce", "unwieldy", "grenade",
        "melee", "versatile", "shock", "gas", "toxin", "rad", "web",
    ]),
    ("general-principles/conditions", [
        "condition", "on fire", "blind", "broken", "flesh wound",
        "seriously injured", "pinned", "webbed", "intoxicated", "insane",
        "seriously", "blaze", "burning",
    ]),
    ("gang-fighters-and-their-weaponry/skills", [
        "skill", "agility", "brawn", "combat", "cunning", "ferocity",
        "leadership", "savant", "shooting", "driving",
    ]),
    ("general-principles/fighter-actions", [
        "action", "activate", "move", "shoot", "charge", "fight",
        "coup de grace", "coup", "stand up", "crawl",
    ]),
    ("the-rules/game-structure/the-action-phase/close-combat", [
        "close combat", "determine attack dice", "attack dice", "reaction attacks",
        "combat sequence", "fight action", "attacks", "melee attack",
    ]),
    ("the-rules/game-structure/the-action-phase/shooting", [
        "shooting", "ranged attack", "firepower", "hit roll", "wound roll",
        "shooting sequence",
    ]),
    ("gang-fighters-and-their-weaponry/index", [
        "characteristic", "strength", "toughness", "wounds", "attacks",
        "initiative", "leadership", "cool", "willpower", "intelligence",
    ]),
    ("campaigns-and-scenarios/the-campaign", [
        "campaign", "territory", "reputation", "credits", "post-battle",
        "advancement", "experience", "xp",
    ]),
    ("trading-post/", [
        "trading post", "trade", "rare trade", "black market", "rarity",
        "availability", "rare", "illegal", "common item", "exclusive item",
        "buy", "purchase", "shopping", "price of", "cost of", "where can i get",
    ]),
    ("trading-post/book-of-peril-badzones-trading-post", [
        "book of peril", "badzone", "bad zone", "special ammunition", "special ammo",
        "ammunition", "ammo", "wargear", "trading post equipment", "personal equipment",
    ]),
]


def get_weather(lat: float, lon: float) -> str:
    """Fetch current conditions and 2-day forecast from Open-Meteo (no API key required)."""
    url = (
        f"https://api.open-meteo.com/v1/forecast"
        f"?latitude={lat}&longitude={lon}"
        f"&current=temperature_2m,relative_humidity_2m,weather_code,wind_speed_10m"
        f"&daily=temperature_2m_max,temperature_2m_min,weather_code,precipitation_probability_max"
        f"&temperature_unit=fahrenheit&wind_speed_unit=mph&forecast_days=2"
    )
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read())
        c = data["current"]
        condition = _WMO_CODES.get(c["weather_code"], f"unknown (code {c['weather_code']})")
        current = (
            f"Current: {condition}, {c['temperature_2m']}°F, "
            f"humidity {c['relative_humidity_2m']}%, wind {c['wind_speed_10m']} mph."
        )
        daily = data.get("daily", {})
        forecast_parts = []
        dates = daily.get("time", [])
        for i, date in enumerate(dates):
            label = "Today" if i == 0 else "Tomorrow"
            cond = _WMO_CODES.get(daily["weather_code"][i], "unknown")
            hi = daily["temperature_2m_max"][i]
            lo = daily["temperature_2m_min"][i]
            rain = daily["precipitation_probability_max"][i]
            forecast_parts.append(
                f"{label} ({date}): {cond}, high {hi}°F, low {lo}°F, {rain}% chance of rain."
            )
        return current + " " + " ".join(forecast_parts)
    except Exception as e:
        return f"Weather data unavailable: {e}"


def web_search(query: str, max_results: int = 5) -> str:
    """Search the web and return results as a formatted string for Claude."""
    try:
        results = list(DDGS().text(query, max_results=max_results))
        if not results:
            return "No results found for that query."
        return "\n\n".join(
            f"{r['title']}\n{r['body']}\nURL: {r['href']}"
            for r in results
        )
    except Exception as e:
        return f"Search unavailable: {e}"


def news_search(query: str, max_results: int = 7) -> str:
    """Search for current news headlines and return structured results for Claude."""
    try:
        results = list(DDGS().news(query, max_results=max_results))
        if not results:
            return "No news results found."
        return "\n\n".join(
            f"{r.get('date', 'Unknown date')} — {r.get('title', 'No title')} "
            f"({r.get('source', 'Unknown source')})\n{r.get('body', '')}"
            for r in results
        )
    except Exception as e:
        return f"News search unavailable: {e}"


def get_curated_news() -> str:
    """Fetch top news specifically scanning Bloomberg and The Guardian UK."""
    sections = []
    
    # 1. Bloomberg
    try:
        b_news = news_search("Bloomberg site:bloomberg.com", max_results=3)
        if "unavailable" in b_news or "No news" in b_news:
            b_news = news_search("Bloomberg", max_results=3)
        sections.append(f"--- BLOOMBERG DISPATCHES ---\n{b_news}")
    except Exception as e:
        sections.append(f"--- BLOOMBERG DISPATCHES ---\nError scanning Bloomberg: {e}")
        
    # 2. The Guardian UK
    try:
        g_rss = _fetch_guardian_rss(max_items=3)
        sections.append(f"--- THE GUARDIAN UK DISPATCHES ---\n{g_rss}")
    except Exception as e:
        sections.append(f"--- THE GUARDIAN UK DISPATCHES ---\nError scanning Guardian UK: {e}")
        
    return "\n\n".join(sections)


def _fetch_guardian_rss(max_items: int = 3) -> str:
    """Fetch headlines from The Guardian UK RSS feed."""
    url = "https://www.theguardian.com/uk/rss"
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7)"})
    content = urllib.request.urlopen(req, timeout=5).read()
    import xml.etree.ElementTree as ET
    root = ET.fromstring(content)
    items = []
    for item in root.findall(".//item")[:max_items]:
        title = item.findtext("title", "").strip()
        desc = item.findtext("description", "").strip()
        clean_desc = re.sub(r'<[^>]+>', '', desc).strip()
        items.append(f"• {title}\n  {clean_desc[:120]}...")
    if not items:
        return news_search("Guardian UK site:theguardian.com", max_results=max_items)
    return "\n".join(items)


# ── Text relevance extraction (shared helper) ─────────────────────────────────
# Used by the offline rules-library engine below to pull the most query-relevant
# paragraphs out of a page's full text.


def _extract_relevant(full_text: str, query: str, max_chars: int = 3000) -> str:
    """Return the most query-relevant paragraphs from a large text block."""
    query_words = [w for w in re.findall(r"\w+", query.lower()) if len(w) > 1]
    words = [w for w in query_words if w not in _RULES_STOPWORDS]
    if not words:
        words = query_words
    phrase = " ".join(words)

    raw_paras = full_text.split("\n\n")
    paragraphs = [p.strip() for p in raw_paras if p.strip()]

    # Score each paragraph by query relevance
    scored = []
    for i, para in enumerate(paragraphs):
        pl = para.lower()
        score = sum(pl.count(w) * 5.0 for w in words)
        lines = para.splitlines()
        first_line = lines[0] if lines else ""
        if first_line.startswith("#"):
            fl_lower = first_line.lower()
            if phrase and phrase in fl_lower:
                score += 500.0
            elif all(w in fl_lower for w in words):
                score += 400.0
            elif any(w in fl_lower for w in words):
                score += 150.0
        if para.startswith("|"):
            score *= 0.01

        if score > 0:
            scored.append((score, i, para))

    if not scored:
        return ""

    # Pick highest scoring paragraphs first to fill character budget!
    scored.sort(key=lambda x: -x[0])
    selected_indices: set = set()
    total = 0

    for score, idx, _ in scored:
        if total >= max_chars:
            break
        # Grab heading + next 3 paragraphs (body text under heading)
        start = idx
        end = min(len(paragraphs), idx + 4)
        for j in range(start, end):
            # stop if we hit the next heading
            if j > idx and paragraphs[j].startswith("#"):
                break
            if j not in selected_indices:
                p_len = len(paragraphs[j])
                if total + p_len <= max_chars:
                    selected_indices.add(j)
                    total += p_len + 2

    sorted_indices = sorted(selected_indices)
    return "\n\n".join(paragraphs[j] for j in sorted_indices)


# ── Generic offline rules library ──────────────────────────────────────────────
# A game's rules live under _rules_dir()/<game>/ as one Markdown file per page,
# plus a manifest.json listing {path, url, title, file}. Rules/ingest_pdf.py
# produces this layout from PDFs; the Necromunda mirror is a web scrape in the
# same shape. We consult the local copy first so lookups work offline and
# instantly. The engine below is game-agnostic — each game just points it at its
# folder (and optionally a keyword→page routing table for concept boosting).

# Generic query filler that would otherwise match unhelpful page titles
# ("how the campaign *works*") instead of the actual rules subject.
_RULES_STOPWORDS = {
    "the", "and", "for", "how", "does", "did", "what", "when", "where", "why",
    "who", "which", "are", "was", "can", "will", "with", "work", "works",
    "working", "use", "used", "using", "get", "gets", "rule", "rules", "ruling",
    "necromunda", "warhammer", "game", "play", "played", "playing", "about",
    "into", "any", "this", "that", "there", "their", "they", "you", "your",
}

_library_cache: dict[str, list] = {}  # folder path -> cached [{title, url, text, headings}]


def _extract_headings(text: str) -> list:
    """Lowercased text of a page's Markdown headings / bold-only lines.

    Rule, stratagem, enhancement and ability NAMES are ingested as headings
    (e.g. '##### **ENEMY WITHIN**'). Capturing them lets a query match a named rule
    even when its words are individually common ('enemy', 'within') and so carry no
    IDF weight — the phrase-as-a-heading is the real signal."""
    heads = []
    for line in text.splitlines():
        s = line.strip()
        if not s:
            continue
        if s.startswith("#") or (s.startswith("**") and s.endswith("**")):
            cleaned = s.lstrip("#").replace("*", "").replace("`", "").strip()
            cleaned = re.sub(r"\s+", " ", cleaned).lower()
            if 2 <= len(cleaned) <= 80:
                heads.append(cleaned)
    return heads

# British/American spelling pairs (-ize/-ise family). GW texts use British spelling
# ("harmonised", "realised"); users/LLMs often type American ("harmonized"), which
# would otherwise miss the rarest, most specific word in a query.
_SPELLING_PAIRS = [
    ("ization", "isation"), ("izations", "isations"), ("izing", "ising"),
    ("ized", "ised"), ("izes", "ises"), ("ize", "ise"),
]


def _spelling_variants(word: str) -> tuple:
    """The word plus its -ize/-ise spelling counterpart, so 'harmonized' matches
    'harmonised' and vice versa."""
    variants = {word}
    for a, b in _SPELLING_PAIRS:
        if word.endswith(a):
            variants.add(word[: -len(a)] + b)
        elif word.endswith(b):
            variants.add(word[: -len(b)] + a)
    return tuple(variants)


def _load_rules_library(base: pathlib.Path) -> list:
    """Load and cache one game's local pages. Empty list if the folder is missing.

    Prefers manifest.json ({file, title, url, path}); falls back to walking every
    *.md file so a folder of loose Markdown still works (titles/URLs then absent)."""
    key = str(base)
    cached = _library_cache.get(key)
    if cached is not None:
        return cached

    idx: list = []
    manifest = base / "manifest.json"
    entries = []
    if manifest.exists():
        try:
            entries = json.loads(manifest.read_text(encoding="utf-8"))
        except Exception as e:
            print(f"[skull] Rules manifest unreadable at {base} ({e}); scanning folder.")
    if not entries and base.exists():
        entries = [{"file": str(p.relative_to(base))} for p in base.rglob("*.md")]

    for e in entries:
        fp = base / e["file"]
        try:
            text = fp.read_text(encoding="utf-8")
        except OSError:
            continue
        title = e.get("title") or fp.stem.replace("-", " ").title()
        idx.append({"title": title, "url": e.get("url", ""), "text": text,
                    "headings": _extract_headings(text)})

    _library_cache[key] = idx
    if idx:
        print(f"[skull] Loaded {len(idx)} local rules pages from {base}")
    return idx


def _search_rules_library(base: pathlib.Path, query: str, routes: list | None = None,
                          label: str = "rules", top_k: int = 2,
                          max_chars: int = 2800) -> str:
    """Rank a local rules library for a query. "" if the library is unavailable.

    Score every page by RELEVANCE, not raw frequency, so a huge page (e.g. an FAQ)
    can't win a topic just by mentioning the words in passing many times:
      • title word hits dominate  — the page whose subject IS the query
      • distinct body words       — breadth of coverage on the page
      • capped frequency          — a little credit for repetition, bounded so
                                    length can't run away with the score
      • concept-route boost       — canonical section for a matched concept

    ``routes`` (optional) is a [(path, [keywords])] table: when a query hits a
    concept whose canonical page's title doesn't contain the word (e.g. "On Fire"
    lives inside "Conditions"), it boosts that page's score.

    Matches are IDF-weighted so a rare, specific term (a unit name like
    "Sanctifiers") outweighs common filler (a faction name repeated on every page,
    or "movement"). In the title, the single rarest matched word dominates — so a
    unit's own datasheet beats a faction-overview page even when the query also
    names the faction (whose two common title words would otherwise sum higher)."""
    index = _load_rules_library(base)
    if not index:
        return ""

    words = [w for w in query.lower().split() if len(w) > 2 and w not in _RULES_STOPWORDS]
    if not words:  # query was all stopwords/short — fall back to the raw terms
        words = [w for w in query.lower().split() if len(w) > 2] or query.lower().split()

    ql = query.lower()
    boosted_paths = []
    if routes:
        boosted_paths = [f"/docs/{path}".rstrip("/")
                         for path, kws in routes if any(kw in ql for kw in kws)]

    # Each word matches either spelling variant (British texts vs American queries).
    var = {w: _spelling_variants(w) for w in words}

    def _in(w: str, text: str) -> bool:
        return any(v in text for v in var[w])

    # First pass: document frequency of each query word → IDF (rarer = heavier).
    n_docs = len(index) or 1
    corpus = [(p["title"].lower(), p["text"].lower(), p) for p in index]
    df = {w: 0 for w in words}
    for tl, bl, _ in corpus:
        combined = tl + " " + bl
        for w in words:
            if _in(w, combined):
                df[w] += 1
    idf = {w: math.log(n_docs / (df[w] + 1)) + 1.0 for w in words}

    # Phrase for heading matching: the significant words in query order. A named
    # rule ("Enemy Within") is a heading, so matching a heading is strong evidence
    # regardless of how common the individual words are.
    phrase = " ".join(words)

    scored = []
    for tl, bl, page in corpus:
        # Coverage is the dominant signal: the IDF-weighted sum over DISTINCT query
        # words found anywhere on the page (title or body). A page that mentions
        # every rare query word beats one that only shares a single common word —
        # even when that common word happens to sit in the other page's title.
        coverage = sum(idf[w] for w in words if _in(w, tl) or _in(w, bl))
        # Title bonus: the page is *about* the query. Use ONLY the single rarest
        # matched title word — so a unit's own datasheet (title "Defiler") outranks
        # its faction's cover/contents page (title "Emperor's Children"), whose two
        # less-rare title words would otherwise sum higher and win.
        t_hits = [idf[w] for w in words if _in(w, tl)]
        title_score = max(t_hits) if t_hits else 0.0
        freq = sum(min(sum(bl.count(v) for v in var[w]), 3) for w in words)  # capped repetition
        # Heading bonus: a page whose heading IS the query (a named rule) wins even
        # when the words are common. Flat, not IDF-weighted, for exactly that reason.
        heading_bonus = 0.0
        for h in page.get("headings", ()):
            if phrase and phrase in h:
                heading_bonus = max(heading_bonus, 300.0 if h == phrase else 180.0)
            elif words and all(_in(w, h) for w in words):
                heading_bonus = max(heading_bonus, 120.0)
        score = coverage * 10 + title_score * 30 + freq + heading_bonus
        if boosted_paths and page["url"] and any(bp in page["url"] for bp in boosted_paths):
            score += 400
        if score > 0:
            scored.append((score, page))

    if not scored:
        return f"No matching rules found in the local {label} library for: {query}"

    scored.sort(key=lambda x: -x[0])
    out = []
    for _, page in scored[:top_k]:
        excerpt = _extract_relevant(page["text"], query, max_chars=max_chars)
        if not excerpt:
            excerpt = page["text"][:max_chars]
        src = page["url"] or page["title"]
        out.append(f"Source: {src}\n\n{excerpt}")
    return "\n\n---\n\n".join(out)


# ── Local Necromunda ruleset (offline library) ────────────────────────────────
# The full Necromunda ruleset (Rules as Written) is mirrored to
# _rules_dir()/necromunda as one Markdown file per page. Offline-only.
_NECRO_DIR = _rules_dir() / "necromunda"


def necromunda_rules(query: str) -> str:
    """Look up Necromunda rules from the local offline library."""
    result = _search_rules_library(_NECRO_DIR, query, routes=_NECRO_ROUTES,
                                   label="Necromunda")
    if not result:
        return ("The Necromunda rules library isn't installed on this device. "
                "Populate _rules_dir()/necromunda with the mirrored ruleset pages.")
    return result


# ── Local Warhammer 40,000 ruleset (offline library) ───────────────────────────
# The 11th-edition core rules, faction packs, and event companions, ingested from
# PDF to _rules_dir()/warhammer40k via Rules/ingest_pdf.py. Offline-only (no live
# fallback — these are PDFs, not a website).
_W40K_DIR = _rules_dir() / "warhammer40k"


def _w40k_faction_note(query: str) -> str:
    """If the query names a datasheet that exists in several faction packs, list them.

    Many units (Defiler, Rhino, Land Raider…) have their own datasheet in multiple
    faction packs. The LLM tends to search without a faction, get one faction's
    datasheet back, and then wrongly conclude the *asked* faction lacks the unit.
    This deterministic note lists every faction that fields a matched unit, so that
    false 'faction X has no such unit' answer can't happen regardless of phrasing."""
    index = _load_rules_library(_W40K_DIR)
    if not index:
        return ""
    ql = query.lower()
    factions: dict[str, set] = {}
    display: dict[str, str] = {}
    for p in index:
        title = p["title"].strip()
        tl = title.lower()
        # Only real datasheets (they carry a reconstructed stat block), and only
        # when the unit's name actually appears in the query.
        if len(tl) < 4 or "(stats):" not in p["text"] or tl not in ql:
            continue
        faction = p["url"].split(",")[0].strip() if p.get("url") else ""
        if faction:
            factions.setdefault(tl, set()).add(faction)
            display[tl] = title
    notes = [
        f"Note: the {display[tl]} datasheet appears in multiple faction packs — "
        f"{', '.join(sorted(facs))} — each with its own version. All of these "
        f"factions field this unit."
        for tl, facs in factions.items() if len(facs) >= 2
    ]
    return "\n".join(notes)


def warhammer40k_rules(query: str) -> str:
    """Look up Warhammer 40,000 (11th edition) rules from the local library."""
    result = _search_rules_library(_W40K_DIR, query, label="Warhammer 40,000")
    if not result:
        return ("The Warhammer 40,000 rules library isn't installed on this device. "
                "Ingest the faction pack / core rules PDFs with Rules/ingest_pdf.py.")
    note = _w40k_faction_note(query)
    return f"{result}\n\n{note}" if note else result


# ── Local NetEpic (Epic 2nd edition) ruleset (offline library) ─────────────────
# NetEpic 5.0 — the community continuation of Epic 2nd Edition — core rules,
# optional rules, and army books, ingested from PDF to _rules_dir()/netepic via
# Rules/ingest_pdf.py. Offline-only. This is a DIFFERENT game from Net Epic
# Armageddon (see netea_rules above), which is why it has its own library.
_NETEPIC_DIR = _rules_dir() / "netepic"


def netepic_rules(query: str) -> str:
    """Look up NetEpic / Epic 2nd edition rules from the local offline library."""
    result = _search_rules_library(_NETEPIC_DIR, query, label="NetEpic")
    if not result:
        return ("The NetEpic rules library isn't installed on this device. "
                "Ingest the NetEpic core rules / army book PDFs with Rules/ingest_pdf.py.")
    return result


# ── Local Net Epic Armageddon (NetEA / Epic 3rd edition) ruleset (offline) ─────
# The NetEA rules, tournament pack, FAQ, and army lists, ingested from PDF to
# _rules_dir()/netea via Rules/ingest_pdf.py. Previously fetched live from
# tp.net-armageddon.org; now offline-only. This is a DIFFERENT game from NetEpic /
# Epic 2nd edition (see netepic_rules above).
_NETEA_DIR = _rules_dir() / "netea"


def netea_rules(query: str) -> str:
    """Look up Net Epic Armageddon (NetEA) rules from the local offline library."""
    result = _search_rules_library(_NETEA_DIR, query, label="NetEA")
    if not result:
        return ("The NetEA rules library isn't installed on this device. "
                "Ingest the NetEA rules / tournament pack / army list PDFs with Rules/ingest_pdf.py.")
    return result
