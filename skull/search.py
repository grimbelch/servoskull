import urllib.request
from html.parser import HTMLParser
from ddgs import DDGS

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
