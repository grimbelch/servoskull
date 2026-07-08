import json
import math
import os
import pathlib
import urllib.request
from html.parser import HTMLParser

from ddgs import DDGS


def _rules_dir() -> pathlib.Path:
    """Resolve the offline rules library dir without depending on skull.config.

    Mirrors config's convention (OMEGA7_DATA_DIR, else the repo root) so it works
    both here and on older deployments that predate the config data-dir refactor.
    RULES_DIR may be a bare name (resolved under the data dir) or an absolute path."""
    repo_root = pathlib.Path(__file__).resolve().parent.parent
    data_dir = pathlib.Path(os.getenv("OMEGA7_DATA_DIR", str(repo_root))).expanduser()
    rules = pathlib.Path(os.getenv("RULES_DIR", "Rules")).expanduser()
    return rules if rules.is_absolute() else data_dir / rules

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

_NECRO_SITE = "necroraw.com.ru"
_NECRO_BASE = f"https://www.{_NECRO_SITE}"

# Keyword → doc page routing. For each entry: (path, [keywords that suggest this page]).
# Order matters: first match wins for the primary page; all matches are collected.
_NECRO_ROUTES = [
    ("gang-fighters-and-their-weaponry/weapon-traits", [
        "trait", "weapon trait", "blaze", "rapid fire", "blast", "template",
        "knockback", "rending", "plentiful", "scarce", "unwieldy", "grenade",
        "melee", "versatile", "shock", "gas", "toxin", "rad",
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


class _TextExtractor(HTMLParser):
    """Strips HTML to plain text, skipping nav/script/style blocks."""

    _SKIP = {"script", "style", "nav", "header", "footer"}

    def __init__(self):
        super().__init__()
        self._parts = []
        self._depth = 0

    def handle_starttag(self, tag, attrs):
        if tag in self._SKIP:
            self._depth += 1

    def handle_endtag(self, tag):
        if tag in self._SKIP and self._depth:
            self._depth -= 1

    def handle_data(self, data):
        if not self._depth:
            s = data.strip()
            if s:
                self._parts.append(s)

    def result(self):
        return "\n".join(self._parts)


def _fetch_text(url: str, max_chars: int = 3000) -> str:
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=10) as resp:
            html = resp.read().decode("utf-8", errors="replace")
        p = _TextExtractor()
        p.feed(html)
        return p.result()[:max_chars]
    except Exception as e:
        return f"Could not fetch {url}: {e}"


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


def _necro_urls_from_keywords(query: str) -> list:
    """Return candidate page URLs by matching query against known keyword routes."""
    q = query.lower()
    urls = []
    for path, keywords in _NECRO_ROUTES:
        if any(kw in q for kw in keywords):
            urls.append(f"{_NECRO_BASE}/docs/{path}")
    return urls


def _necro_urls_from_ddg(query: str) -> list:
    """Try DDG searches and return any necroraw.com.ru URLs found."""
    for q in [f'necroraw.com.ru {query}', f'site:{_NECRO_SITE} {query}']:
        try:
            results = list(DDGS().text(q, max_results=5))
            urls = [r["href"] for r in results if _NECRO_SITE in r.get("href", "")]
            if urls:
                return urls
        except Exception:
            continue
    return []


# ── Net Epic Armageddon ───────────────────────────────────────────────────────

_NETEA_URL = "https://tp.net-armageddon.org/tournament-pack/"
_netea_cache: str = ""


def _get_netea_text() -> str:
    global _netea_cache
    if not _netea_cache:
        print("[skull] Fetching NetEA rules (one-time cache)...")
        _netea_cache = _fetch_text(_NETEA_URL, max_chars=300_000)
    return _netea_cache


def _extract_relevant(full_text: str, query: str, max_chars: int = 3000) -> str:
    """Return the most query-relevant paragraphs from a large text block."""
    words = [w for w in query.lower().split() if len(w) > 2]
    # Drop Markdown table-separator / empty-cell rows (just |, -, spaces): they carry
    # no rules text and otherwise fill excerpts with rows of "| --- | --- |".
    paragraphs = [p.strip() for p in full_text.split("\n")
                  if p.strip() and set(p.strip()) - set("|- ")]

    # Score each paragraph by how many query words it contains
    scored = []
    for i, para in enumerate(paragraphs):
        pl = para.lower()
        score = sum(pl.count(w) for w in words)
        if score > 0:
            scored.append((score, i, para))

    if not scored:
        return ""

    # Pick top paragraphs by score; include a line of context before each match
    scored.sort(key=lambda x: -x[0])
    seen_indices: set = set()
    result_parts: list = []
    total = 0

    for _, idx, _ in scored:
        if total >= max_chars:
            break
        # grab up to 3 lines of context around the match
        start = max(0, idx - 1)
        end = min(len(paragraphs), idx + 3)
        for j in range(start, end):
            if j not in seen_indices:
                seen_indices.add(j)
                result_parts.append((j, paragraphs[j]))

    result_parts.sort(key=lambda x: x[0])
    return "\n".join(p for _, p in result_parts)[:max_chars]


def netea_rules(query: str) -> str:
    """Look up Net Epic Armageddon rules from the NetEA Tournament Pack."""
    text = _get_netea_text()
    if text.startswith("Could not fetch"):
        return text
    excerpt = _extract_relevant(text, query)
    if not excerpt:
        return f"No relevant rules found in the NetEA Tournament Pack for: {query}"
    return f"Source: {_NETEA_URL}\n\n{excerpt}"


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

_library_cache: dict[str, list] = {}  # folder path -> cached [{title, url, text}]


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
        idx.append({"title": title, "url": e.get("url", ""), "text": text})

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

    # First pass: document frequency of each query word → IDF (rarer = heavier).
    n_docs = len(index) or 1
    corpus = [(p["title"].lower(), p["text"].lower(), p) for p in index]
    df = {w: 0 for w in words}
    for tl, bl, _ in corpus:
        combined = tl + " " + bl
        for w in words:
            if w in combined:
                df[w] += 1
    idf = {w: math.log(n_docs / (df[w] + 1)) + 1.0 for w in words}

    scored = []
    for tl, bl, page in corpus:
        # Coverage is the dominant signal: the IDF-weighted sum over DISTINCT query
        # words found anywhere on the page (title or body). A page that mentions
        # every rare query word beats one that only shares a single common word —
        # even when that common word happens to sit in the other page's title.
        coverage = sum(idf[w] for w in words if w in tl or w in bl)
        # Title bonus: the page is *about* the query. The rarest matched title word
        # dominates, so a specific unit's own datasheet outranks a faction-overview
        # page whose two common title words would otherwise sum higher.
        t_hits = sorted((idf[w] for w in words if w in tl), reverse=True)
        title_score = (t_hits[0] + 0.3 * sum(t_hits[1:])) if t_hits else 0.0
        freq = sum(min(bl.count(w), 3) for w in words)          # capped repetition
        score = coverage * 10 + title_score * 30 + freq
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
# The full NecroRAW ruleset is mirrored to _rules_dir()/necromunda; the live-fetch
# path below is kept only as a fallback when the mirror is absent.
_NECRO_DIR = _rules_dir() / "necromunda"


def _necromunda_rules_local(query: str) -> str:
    """Search the local Necromunda mirror; return "" if the mirror is unavailable."""
    return _search_rules_library(_NECRO_DIR, query, routes=_NECRO_ROUTES,
                                 label="Necromunda")


def _necromunda_rules_online(query: str) -> str:
    """Fallback: look up Necromunda rules live on necroraw.com.ru."""
    def _fetch_pages(urls: list) -> list:
        pages = []
        for url in urls[:4]:
            text = _fetch_text(url)
            if text and not text.startswith("Could not fetch") and len(text) > 200:
                pages.append(f"Source: {url}\n\n{text}")
            if len(pages) == 2:
                break
        return pages

    # Priority 1: keyword routing to known section pages (fast, reliable)
    pages = _fetch_pages(_necro_urls_from_keywords(query))

    # Priority 2: DDG search — used both when no route matched and when the routed
    # pages failed to fetch (e.g. a section path went stale), so a bad route never
    # silently swallows a query that search could have answered.
    if not pages:
        pages = _fetch_pages(_necro_urls_from_ddg(query))

    if pages:
        return "\n\n---\n\n".join(pages)
    return f"No matching rules pages found on {_NECRO_SITE} for: {query}"


def necromunda_rules(query: str) -> str:
    """Look up Necromunda rules, preferring the offline local mirror.

    Reads from config.RULES_DIR/necromunda if it has been populated; only if that
    mirror is missing does it fall back to fetching necroraw.com.ru live."""
    local = _necromunda_rules_local(query)
    if local:
        return local
    return _necromunda_rules_online(query)


# ── Local Warhammer 40,000 ruleset (offline library) ───────────────────────────
# The 11th-edition core rules, faction packs, and event companions, ingested from
# PDF to _rules_dir()/warhammer40k via Rules/ingest_pdf.py. Offline-only (no live
# fallback — these are PDFs, not a website).
_W40K_DIR = _rules_dir() / "warhammer40k"


def warhammer40k_rules(query: str) -> str:
    """Look up Warhammer 40,000 (11th edition) rules from the local library."""
    result = _search_rules_library(_W40K_DIR, query, label="Warhammer 40,000")
    if result:
        return result
    return ("The Warhammer 40,000 rules library isn't installed on this device. "
            "Ingest the faction pack / core rules PDFs with Rules/ingest_pdf.py.")
