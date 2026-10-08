"""Necromunda Skirmish rules lookup, over the extracted rules database.

Prose questions are answered from the ``rule_sections`` layer through FTS5, with
the page the answer came from quoted alongside it so a ruling can be checked
against the book. Questions about a specific weapon's numbers go to
``rules_tools`` instead, which reads the columns directly: the whole point of
extracting those tables by geometry is that a stat never has to be re-read out
of prose.
"""
from __future__ import annotations

import re
import sqlite3

from . import db as necro_db
from . import rules_schema

# Filler that would otherwise match an unhelpful heading instead of the subject.
_STOPWORDS = {
    "the", "and", "for", "how", "does", "did", "what", "when", "where", "why",
    "who", "which", "are", "was", "can", "will", "with", "work", "works",
    "working", "use", "used", "using", "get", "gets", "rule", "rules", "ruling",
    "necromunda", "game", "play", "played", "playing", "about", "into", "any",
    "this", "that", "there", "their", "they", "you", "your", "its", "have",
    "has", "then", "than", "from", "but", "not", "all", "one", "two",
}

_WORD = re.compile(r"[A-Za-z0-9']+")

_NOT_INSTALLED = (
    "The Necromunda rules library isn't installed on this device. Build it with "
    "`python -m games.necromunda.extract.ingest <core rulebook PDF>`."
)


def current_rulebook(conn: sqlite3.Connection):
    """The book being consulted: the earliest, since only one is ingested.

    Every read is scoped to it. Rows belonging to no rulebook at all are purged
    on open, but scoping is what stops a stray one being quoted in the first
    place -- and the symptom of that was every answer arriving twice.
    """
    return conn.execute(
        "SELECT id, title, edition, page_offset FROM rulebooks"
        " ORDER BY id LIMIT 1").fetchone()


def _terms(query: str) -> list[str]:
    words = [w.lower() for w in _WORD.findall(query)]
    keep = [w for w in words if len(w) > 2 and w not in _STOPWORDS]
    return keep or [w for w in words if len(w) > 2] or words


def _match_expr(terms: list[str], join: str) -> str:
    # Every term is quoted: FTS5 treats bare punctuation and words like "NOT" as
    # operators, and a user's phrasing must never be read as query syntax.
    return f" {join} ".join('"' + t.replace('"', '') + '"' for t in terms)


def _fts_search(conn: sqlite3.Connection, terms: list[str], limit: int,
                book_id: int) -> list[sqlite3.Row]:
    """Rows for a query, preferring every term present over any term present."""
    for join in ("AND", "OR"):
        if join == "AND" and len(terms) == 1:
            continue
        try:
            rows = conn.execute(
                "SELECT title, body, kind, page, ref_table, ref_id FROM rule_search"
                " WHERE rule_search MATCH ? AND rulebook_id = ?"
                " ORDER BY bm25(rule_search, 4.0, 1.0)"
                " LIMIT ?", (_match_expr(terms, join), book_id, limit)).fetchall()
        except sqlite3.Error:
            return []
        if rows:
            return rows
    return []


def _like_search(conn: sqlite3.Connection, terms: list[str], limit: int,
                 book_id: int) -> list[sqlite3.Row]:
    """Fallback for a SQLite build without FTS5."""
    clause = " OR ".join("(title LIKE ? OR body_md LIKE ?)" for _ in terms)
    args: list[str] = []
    for term in terms:
        args.extend([f"%{term}%", f"%{term}%"])
    return conn.execute(
        f"SELECT title, body_md AS body, kind, page_start AS page,"
        f" 'rule_sections' AS ref_table, id AS ref_id FROM rule_sections"
        f" WHERE rulebook_id = ? AND body_md != '' AND ({clause}) LIMIT ?",
        (book_id, *args, limit)).fetchall()


def _excerpt(body: str, terms: list[str], max_chars: int) -> str:
    """The most relevant paragraphs of a section, best first.

    Whole paragraphs are returned rather than matching lines: a rule's sentences
    depend on each other, and clipping one mid-thought is how a lookup ends up
    quoting half a rule as though it were the whole of it.
    """
    paragraphs = [p.strip() for p in re.split(r"\n\s*\n", body) if p.strip()]
    if not paragraphs:
        return ""
    scored = []
    for index, para in enumerate(paragraphs):
        lower = para.lower()
        score = sum(lower.count(t) for t in terms)
        scored.append((score, index, para))
    if not any(s for s, _, _ in scored):
        joined = "\n\n".join(paragraphs)
        return joined[:max_chars]
    scored.sort(key=lambda t: (-t[0], t[1]))
    out: list[str] = []
    total = 0
    for score, _, para in scored:
        if score == 0 or total >= max_chars:
            break
        out.append(para)
        total += len(para)
    return "\n\n".join(out)[:max_chars]


def necromunda_rules(query: str, top_k: int = 3, max_chars: int = 1400) -> str:
    """Look up Necromunda Skirmish rules from the local offline library."""
    if not query or not query.strip():
        return "Ask about a specific rule, weapon, skill or phase."
    try:
        conn = necro_db.connect(create=False)
    except (FileNotFoundError, sqlite3.Error):
        return _NOT_INSTALLED
    try:
        book = current_rulebook(conn)
        if not book:
            return _NOT_INSTALLED

        terms = _terms(query)
        rows = (_fts_search(conn, terms, top_k, book["id"])
                if rules_schema.has_fts5(conn)
                else _like_search(conn, terms, top_k, book["id"]))
        if not rows:
            return (f"No matching rules found in {book['title']} for: {query}")

        parts = []
        for row in rows:
            if row["ref_table"] == "rule_weapons":
                weapon = conn.execute(
                    "SELECT * FROM rule_weapons WHERE id = ? AND rulebook_id = ?",
                    (row["ref_id"], book["id"])).fetchone()
                if weapon:
                    parts.append(_format_weapon(weapon, book))
                    continue
            body = _excerpt(row["body"], terms, max_chars)
            if not body:
                continue
            parts.append(f"{row['title']} ({book['title']}, "
                         f"p{printed_page(row['page'], book)})\n\n{body}")
        if not parts:
            return f"No matching rules found in {book['title']} for: {query}"
        return "\n\n---\n\n".join(parts)
    finally:
        conn.close()


def printed_page(page: int, book: sqlite3.Row) -> int:
    """The page number printed on the page, from the PDF's index.

    The scan opens with front matter the printed folios do not count, so the two
    run one apart in this book. Citing the index would send a reader to the
    wrong page of their own copy; the offset is measured at ingest from the
    contents list.
    """
    try:
        offset = book["page_offset"] or 0
    except (IndexError, KeyError):
        offset = 0
    return max(1, int(page) - int(offset))


def _format_weapon(row: sqlite3.Row, book: sqlite3.Row) -> str:
    """A weapon profile as the book prints it, with unprinted cells named as such."""
    def cell(value: str) -> str:
        value = (value or "").strip()
        return value if value and value not in {"-", "—"} else "not printed"

    lines = [
        f"{row['name']} — {row['category'] or 'weapon profile'} "
        f"({book['title']}, p{printed_page(row['page'], book)})",
        f"  Short range: {cell(row['sr_text'])}    Long range: {cell(row['lr_text'])}",
        f"  Strength: {cell(row['str_text'])}    AP: {cell(row['ap_text'])}"
        f"    Lethality: {cell(row['lethality_text'])}",
        f"  Traits: {row['traits'] or 'none printed'}",
    ]
    # Not everything with a profile is for sale: a Wyrd power's conjured weapon,
    # a skill's attack and the unarmed profile have no price at all, and saying
    # "not printed credits" of them reads as though the book forgot.
    if (row["creds_text"] or "").strip() not in {"", "-", "\u2014"}:
        lines.append(f"  Cost: {cell(row['creds_text'])} credits, Trading Post "
                     f"{cell(row['tp_text'])}")
    else:
        lines.append("  Not bought from the Trading Post: no cost is printed for it.")
    if row["is_variant"]:
        lines.append("  This is a special ammunition line: its cost is added to the "
                     "weapon it is bought for.")
    if row["needs_review"]:
        lines.append("  Note: this profile is printed inside body text rather than in "
                     "a table, so its trait list may have picked up neighbouring "
                     "words. The numbers are reliable; check the traits on p"
                     f"{printed_page(row['page'], book)}.")
    return "\n".join(lines)
