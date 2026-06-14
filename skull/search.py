import json
import urllib.request
from html.parser import HTMLParser
from ddgs import DDGS

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
    paragraphs = [p.strip() for p in full_text.split("\n") if p.strip()]

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


def necromunda_rules(query: str) -> str:
    """Look up Necromunda rules on necroraw.com.ru and return page text."""
    # Priority 1: keyword routing to known section pages (fast, reliable)
    urls = _necro_urls_from_keywords(query)

    # Priority 2: DDG search (slower, may miss the site)
    if not urls:
        urls = _necro_urls_from_ddg(query)

    pages = []
    for url in urls[:4]:
        text = _fetch_text(url)
        if text and not text.startswith("Could not fetch") and len(text) > 200:
            pages.append(f"Source: {url}\n\n{text}")
        if len(pages) == 2:
            break

    if pages:
        return "\n\n---\n\n".join(pages)
    return f"No matching rules pages found on {_NECRO_SITE} for: {query}"
