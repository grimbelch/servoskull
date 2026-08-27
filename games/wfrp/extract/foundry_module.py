"""Ingest a WFRP adventure module from its Foundry VTT package.

Run as::

    python -m games.wfrp.extract.foundry_module rnhd.json \\
        --module-dir /path/to/Data/modules/wfrp4e-rnhd \\
        --slug rough-nights-and-hard-days

The JSON is produced by ``foundry_export.cjs``, which reads the module's
LevelDB packs on the Foundry host. Foundry ships the same book as structured
documents -- journal pages with real headings, actors with real characteristic
numbers, and ``@UUID`` links naming every NPC a scene involves -- so this
replaces the previous PDF pipeline, which had to infer all of that from glyph
positions.

Everything under ``module_*`` is rebuilt from scratch on each run. Per-campaign
state in ``campaign_module_*`` is keyed by module id and is left untouched, so a
re-extraction does not disturb a campaign in progress.
"""
from __future__ import annotations

import argparse
import hashlib
import html
import json
import os
import re
import shutil
import sqlite3
from dataclasses import dataclass, field
from datetime import datetime, timezone
from html.parser import HTMLParser
from typing import Iterator, Optional

from .. import module_schema
from .map_keys import apply_map_keys

EXTRACTOR_VERSION = "3.0-foundry"

_PLOT_NUMBER_RE = re.compile(r"^plot\s*(\d+)", re.IGNORECASE)
# Events name the plots they advance inline -- "A small boat arrives (Plot 2)" --
# so the reference is searched for anywhere in the description.
_PLOT_REF_RE = re.compile(r"\bplot\s*(\d+)", re.IGNORECASE)
_CLOCK_RE = re.compile(
    r"^(?P<hour>\d{1,2})(?:[:.](?P<minute>\d{2}))?\s*(?P<meridiem>a\.?m\.?|p\.?m\.?)",
    re.IGNORECASE,
)
# Foundry embeds cross-references as @UUID[Actor.abc]{Label} or
# @UUID[Compendium.wfrp4e-rnhd.actors.abc]{Label}. The trailing id is the
# document id in both forms.
_UUID_RE = re.compile(r"@UUID\[([^\]]+)\](?:\{([^}]*)\})?")

# Pages whose children are rooms rather than generic subsections.
_LOCATION_TITLES = {
    "theinn", "thecourthouse", "theoperahouse", "thecastle", "themansion",
}
_RESOLUTION_TITLES = {"resolution", "concludingtheadventure"}

_IMAGE_EXTENSIONS = {".webp", ".png", ".jpg", ".jpeg", ".gif", ".svg"}

# Characteristic abbreviations as Foundry stores them, mapped to our columns.
# `intl` avoids colliding with the SQL keyword; `m` and `w` come from elsewhere
# in the actor document.
_CHARACTERISTICS = {
    "ws": "ws", "bs": "bs", "s": "s", "t": "t", "i": "i",
    "ag": "ag", "dex": "dex", "int": "intl", "wp": "wp", "fel": "fel",
}


def slugify(text: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", (text or "").lower()).strip("-")
    return slug[:80] or "section"


def _match_key(text: str) -> str:
    """Collapse a title to a comparable key, ignoring punctuation and case."""
    return re.sub(r"[^a-z0-9]+", "", (text or "").lower())


def time_to_minutes(label: str) -> Optional[int]:
    """Map an in-fiction time label onto minutes since the adventure's noon start.

    The adventures run from an afternoon through to the following morning, so a
    plain clock sort puts "4:30am" before "9:30pm". Anchoring at noon and rolling
    past midnight keeps the timeline monotonic.
    """
    text = (label or "").strip().lower()
    if not text:
        return None
    if text.startswith("midnight") or text.startswith("12 midnight"):
        return 12 * 60
    if text.startswith("noon") or text.startswith("midday"):
        return 0

    match = _CLOCK_RE.match(text)
    if not match:
        return None
    hour = int(match.group("hour")) % 12
    minute = int(match.group("minute") or 0)
    if match.group("meridiem").startswith("p"):
        hour += 12
    minutes = hour * 60 + minute
    # Anchor at noon; anything earlier in clock terms is the following morning.
    return minutes - 12 * 60 if minutes >= 12 * 60 else minutes + 12 * 60


def file_sha256(path: str) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _plain_text(markdown: str) -> str:
    return re.sub(r"[#*_`|]", "", markdown or "")


# ── HTML → Markdown ──────────────────────────────────────────────────────────


class _MarkdownWriter(HTMLParser):
    """Render Foundry's journal HTML as Markdown.

    Foundry stores journal prose as a small, well-formed subset of HTML: block
    text, lists, tables, inline emphasis, and ``@UUID`` links. Converting it to
    Markdown keeps the database renderer-agnostic and keeps the FTS index free
    of tag soup. Headings are *not* emitted, because the caller splits pages on
    them before this runs.
    """

    _BLOCKS = {"p", "div", "section", "blockquote", "figure", "figcaption", "br"}

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self._list_stack: list[dict] = []
        self._row: list[str] = []
        self._cell: Optional[list[str]] = None
        self._table: list[list[str]] = []
        self._in_table = False

    # Text either lands in the current table cell or in the document body.
    def _emit(self, text: str) -> None:
        (self._cell if self._cell is not None else self.parts).append(text)

    def handle_starttag(self, tag, attrs):
        if tag in ("strong", "b"):
            self._emit("**")
        elif tag in ("em", "i"):
            self._emit("*")
        elif tag == "li":
            depth = max(len(self._list_stack) - 1, 0)
            frame = self._list_stack[-1] if self._list_stack else {"ordered": False, "n": 0}
            frame["n"] = frame.get("n", 0) + 1
            marker = f"{frame['n']}." if frame.get("ordered") else "-"
            self._emit("\n" + "  " * depth + marker + " ")
        elif tag in ("ul", "ol"):
            self._list_stack.append({"ordered": tag == "ol", "n": 0})
            self._emit("\n")
        elif tag == "table":
            self._in_table, self._table = True, []
        elif tag == "tr" and self._in_table:
            self._row = []
        elif tag in ("td", "th") and self._in_table:
            self._cell = []
        elif tag == "img":
            source = dict(attrs).get("src", "")
            if source:
                self._emit(f"\n![]({source})\n")
        elif tag in self._BLOCKS:
            self._emit("\n\n" if tag != "br" else "\n")

    def handle_endtag(self, tag):
        if tag in ("strong", "b"):
            self._emit("**")
        elif tag in ("em", "i"):
            self._emit("*")
        elif tag in ("ul", "ol"):
            if self._list_stack:
                self._list_stack.pop()
            self._emit("\n")
        elif tag in ("td", "th") and self._in_table:
            self._row.append(re.sub(r"\s+", " ", "".join(self._cell or [])).strip())
            self._cell = None
        elif tag == "tr" and self._in_table:
            if self._row:
                self._table.append(self._row)
            self._row = []
        elif tag == "table":
            self._flush_table()
        elif tag in self._BLOCKS:
            self._emit("\n\n")

    def handle_data(self, data):
        self._emit(data)

    def _flush_table(self) -> None:
        """Close a table, rendering it as a Markdown pipe table."""
        self._in_table = False
        rows, self._table = self._table, []
        if not rows:
            return
        width = max(len(row) for row in rows)
        rows = [row + [""] * (width - len(row)) for row in rows]
        header, body = rows[0], rows[1:]
        lines = ["| " + " | ".join(header) + " |",
                 "| " + " | ".join(["---"] * width) + " |"]
        lines += ["| " + " | ".join(row) + " |" for row in body]
        self.parts.append("\n\n" + "\n".join(lines) + "\n\n")

    def result(self) -> str:
        text = "".join(self.parts)
        # Foundry links carry their own display text; keep the label only.
        text = _UUID_RE.sub(lambda m: m.group(2) or m.group(1).split(".")[-1], text)
        text = re.sub(r"[ \t]+", " ", text)
        text = re.sub(r" *\n *", "\n", text)
        text = re.sub(r"\n{3,}", "\n\n", text)
        return text.strip()


def html_to_markdown(source: str) -> str:
    writer = _MarkdownWriter()
    writer.feed(source or "")
    writer.close()
    return writer.result()


def _strip_tags(source: str) -> str:
    text = _UUID_RE.sub(lambda m: m.group(2) or "", source or "")
    return html.unescape(re.sub(r"<[^>]+>", "", text)).strip()


# ── section tree ─────────────────────────────────────────────────────────────


@dataclass
class Section:
    """One node of the module outline."""

    level: int
    ordinal: int
    kind: str
    title: str
    body_md: str = ""
    slug: str = ""
    doc_order: int = 0
    parent: Optional["Section"] = None
    children: list["Section"] = field(default_factory=list)
    # Foundry document ids, used to resolve @UUID references back to sections.
    source_ids: tuple[str, ...] = ()

    def add(self, child: "Section") -> "Section":
        child.parent = self
        child.ordinal = len(self.children)
        self.children.append(child)
        return child

    def walk(self) -> Iterator["Section"]:
        yield self
        for child in self.children:
            yield from child.walk()

    def ancestor_of_kind(self, kind: str) -> Optional["Section"]:
        node = self.parent
        while node is not None:
            if node.kind == kind:
                return node
            node = node.parent
        return None

    @property
    def word_count(self) -> int:
        return len(self.body_md.split())


_HEADING_RE = re.compile(r"<(h[1-6])[^>]*>(.*?)</\1\s*>", re.IGNORECASE | re.DOTALL)


def _split_on_headings(source: str) -> tuple[str, list[tuple[int, str, str]]]:
    """Split page HTML into a preamble and a list of (level, title, html) blocks."""
    matches = list(_HEADING_RE.finditer(source or ""))
    if not matches:
        return source or "", []
    preamble = source[: matches[0].start()]
    blocks = []
    for index, match in enumerate(matches):
        end = matches[index + 1].start() if index + 1 < len(matches) else len(source)
        title = _strip_tags(match.group(2))
        if not title:
            continue
        blocks.append((int(match.group(1)[1]), title, source[match.end():end]))
    return preamble, blocks


def _child_kind(page_key: str, title: str) -> str:
    """Classify a heading inside a page by the page it belongs to."""
    if page_key == "plotsummaries":
        return "plot" if _PLOT_NUMBER_RE.match(title) else "section"
    if page_key == "events":
        return "event" if time_to_minutes(title) is not None else "event_note"
    if page_key in _LOCATION_TITLES:
        return "room"
    return "section"


def _page_kind(name: str, page_type: str) -> str:
    key = _match_key(name)
    if page_type == "image":
        return "plate"
    if key in _LOCATION_TITLES:
        return "location"
    if key in _RESOLUTION_TITLES:
        return "resolution"
    if key == "plotsummaries":
        return "plots"
    if key == "events":
        return "events"
    return "section"


def build_sections(journals: list[dict]) -> list[Section]:
    """Turn journal entries and their pages into the module outline.

    Foundry orders documents by a sparse integer ``sort`` key rather than by
    position in the pack, so both levels are sorted explicitly. That order is
    the printed order of the book.
    """
    roots: list[Section] = []
    for index, journal in enumerate(sorted(journals, key=lambda j: (j["sort"], j["name"]))):
        chapter = Section(
            level=1, ordinal=index, kind="chapter", title=journal["name"],
            slug=slugify(journal["name"]), source_ids=(journal["_id"],),
        )
        roots.append(chapter)

        for page in sorted(journal["pages"], key=lambda p: (p["sort"], p["name"])):
            preamble, blocks = _split_on_headings(page["html"])
            page_node = chapter.add(Section(
                level=2, ordinal=0, kind=_page_kind(page["name"], page["type"]),
                title=page["name"], body_md=html_to_markdown(preamble),
                slug=slugify(page["name"]), source_ids=(page["_id"],),
            ))

            page_key = _match_key(page["name"])
            # Headings nest by their own level, so an <h4> under an <h3> becomes
            # a child rather than a sibling.
            stack: list[tuple[int, Section]] = []
            for heading_level, title, body in blocks:
                while stack and stack[-1][0] >= heading_level:
                    stack.pop()
                parent = stack[-1][1] if stack else page_node
                node = parent.add(Section(
                    level=parent.level + 1, ordinal=0,
                    kind=_child_kind(page_key, title), title=title,
                    body_md=html_to_markdown(body), slug=slugify(title),
                ))
                stack.append((heading_level, node))

    order = 0
    for root in roots:
        for node in root.walk():
            node.doc_order = order
            order += 1
    return roots


# ── NPCs ─────────────────────────────────────────────────────────────────────


def _detail(actor: dict, key: str, default: str = "") -> str:
    entry = actor.get("system", {}).get("details", {}).get(key)
    if isinstance(entry, dict):
        return str(entry.get("value") or default)
    return str(entry or default)


def _items_named(actor: dict, item_type: str, value_key: str = "") -> list[dict]:
    out = []
    for item in actor.get("items", []):
        if item.get("type") != item_type:
            continue
        entry: dict = {"name": item.get("name", "")}
        if value_key:
            holder = item.get("system", {}).get(value_key)
            if isinstance(holder, dict):
                entry["value"] = holder.get("value")
            elif holder is not None:
                entry["value"] = holder
        out.append(entry)
    return out


def _profile_row(actor: dict) -> dict:
    """Pull one printed characteristic profile out of a Foundry actor."""
    system = actor.get("system", {})
    characteristics = system.get("characteristics", {})
    stats = {
        column: (characteristics.get(abbr) or {}).get("value")
        for abbr, column in _CHARACTERISTICS.items()
    }
    move = system.get("details", {}).get("move")
    stats["m"] = move.get("value") if isinstance(move, dict) else move
    stats["w"] = (system.get("status", {}).get("wounds") or {}).get("max")

    # Trappings are everything carried that is not a rules construct.
    trappings = [
        {"name": item.get("name", "")}
        for item in actor.get("items", [])
        if item.get("type") in {"weapon", "armour", "trapping", "money", "ammunition"}
    ]
    return {
        "stats": stats,
        "skills": _items_named(actor, "skill", "advances"),
        "talents": _items_named(actor, "talent", "advances"),
        "traits": _items_named(actor, "trait"),
        "trappings": trappings,
        "spells": _items_named(actor, "spell"),
    }


def _npc_title(actor: dict) -> str:
    """Recreate the printed stat-block header, e.g. "Noble Lord (Gold 7)"."""
    careers = [i.get("name", "") for i in actor.get("items", []) if i.get("type") == "career"]
    status = _detail(actor, "status")
    lead = careers[0] if careers else _detail(actor, "species").title()
    return f"{lead} ({status})".strip() if status else lead


def _npc_description(actor: dict) -> str:
    """Prefer the biography; fall back to GM notes, which is where this module
    puts its NPC prose."""
    for key in ("biography", "gmnotes"):
        text = html_to_markdown(_detail(actor, key))
        if text:
            return text
    return ""


# ── assets ───────────────────────────────────────────────────────────────────


@dataclass
class Asset:
    kind: str
    path: str
    caption: str = ""
    source: str = ""          # Foundry path, e.g. modules/wfrp4e-rnhd/assets/...
    width: int = 0
    height: int = 0
    sha256: str = ""


def _asset_kind(relative: str) -> str:
    folder = relative.split("/")[1] if "/" in relative else ""
    if folder == "maps":
        return "map"
    if folder in ("actors", "tokens"):
        return "portrait"
    # `scenes/` holds Foundry's own scene thumbnails, which are small
    # previews of the artwork already present in `maps/`, not maps themselves.
    return "art"


_RESOLUTION_TOKEN_RE = re.compile(r"^\d+x\d+$")


def _caption_for(relative: str) -> str:
    """Turn an artwork filename into something printable.

    Files are named for sorting rather than display -- ``01-3feathers-
    3268x4662.webp`` -- so ordering prefixes and pixel dimensions are dropped.
    """
    stem = os.path.splitext(os.path.basename(relative))[0]
    stem = re.sub(r"^\d+-", "", stem)
    words = [w for w in stem.split("-") if w and not _RESOLUTION_TOKEN_RE.match(w)]
    if words and words[-1].lower() in ("unlabeled", "unlabelled"):
        return " ".join(w.title() for w in words[:-1]) + " (Unlabelled)"
    return " ".join(word.title() for word in words)


def _image_size(path: str) -> tuple[int, int]:
    try:
        from PIL import Image  # Pillow is already a runtime dependency.

        with Image.open(path) as image:
            return image.size
    except Exception:
        return (0, 0)


def collect_assets(
    module_dir: str,
    asset_paths: list[str],
    image_dir: str,
    package_id: str,
    scenes: Optional[list[dict]] = None,
) -> list[Asset]:
    """Copy the module's artwork into the module image directory.

    The files are licensed Cubicle 7 content, so they are copied out of the
    Foundry install at ingest time and git-ignored rather than committed.

    ``package_id`` is the Foundry package id (``wfrp4e-rnhd``), which is what
    documents use to reference artwork; it is taken from the export rather than
    from the directory name, which may differ on a working copy.
    """
    os.makedirs(image_dir, exist_ok=True)
    # Scene thumbnails are named for the scene's document id, so the readable
    # name has to be looked up.
    scene_names = {scene["_id"]: scene["name"] for scene in (scenes or [])}
    assets: list[Asset] = []

    for relative in sorted(asset_paths):
        if os.path.splitext(relative)[1].lower() not in _IMAGE_EXTENSIONS:
            continue
        source = os.path.join(module_dir, relative)
        if not os.path.isfile(source):
            continue
        destination = os.path.join(image_dir, relative.replace("assets/", "", 1))
        os.makedirs(os.path.dirname(destination), exist_ok=True)
        shutil.copyfile(source, destination)

        caption = _caption_for(relative)
        scene_id = os.path.basename(relative).split("-")[0]
        if scene_id in scene_names:
            caption = f"{scene_names[scene_id]} (thumbnail)"

        width, height = _image_size(destination)
        assets.append(Asset(
            kind=_asset_kind(relative),
            path=destination,
            caption=caption,
            source=f"modules/{package_id}/{relative}",
            width=width, height=height, sha256=file_sha256(destination),
        ))
    return assets


# ── database writer ──────────────────────────────────────────────────────────


class Ingestor:
    """Writes one exported module into the database."""

    def __init__(self, conn: sqlite3.Connection, module_id: int):
        self.conn = conn
        self.module_id = module_id
        self.section_ids: dict[int, int] = {}      # doc_order -> module_sections.id
        self.section_by_slug: dict[str, int] = {}
        self.chapter_by_slug: dict[str, int] = {}
        self.npc_ids: dict[str, int] = {}          # foundry actor id -> module_npcs.id
        self.asset_ids: dict[str, int] = {}        # foundry path -> module_assets.id
        # Foundry document id -> (section_id, chapter_id), for @UUID resolution.
        self.section_by_source: dict[str, tuple[int, Optional[int]]] = {}

    # ── sections ─────────────────────────────────────────────────────────────

    def write_sections(self, roots: list[Section]) -> None:
        ordered = sorted(
            (node for root in roots for node in root.walk()), key=lambda n: n.doc_order
        )
        for section in ordered:
            parent_id = (
                self.section_ids.get(section.parent.doc_order) if section.parent else None
            )
            chapter = section if section.kind == "chapter" else section.ancestor_of_kind("chapter")
            chapter_id = self.section_ids.get(chapter.doc_order) if chapter else None

            cursor = self.conn.execute(
                """
                INSERT INTO module_sections
                    (module_id, parent_id, chapter_id, level, ordinal, doc_order,
                     kind, slug, title, body_md, page_start, page_end, word_count,
                     accent)
                VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                """,
                (
                    self.module_id, parent_id, chapter_id, section.level,
                    section.ordinal, section.doc_order, section.kind, section.slug,
                    section.title, section.body_md, 0, 0, section.word_count, "",
                ),
            )
            row_id = cursor.lastrowid
            self.section_ids[section.doc_order] = row_id
            self.section_by_slug.setdefault(section.slug, row_id)
            if section.kind == "chapter":
                self.chapter_by_slug[section.slug] = row_id
            for source_id in section.source_ids:
                self.section_by_source[source_id] = (row_id, chapter_id)

    # ── plots and events ─────────────────────────────────────────────────────

    def write_plots_and_events(self, roots: list[Section]) -> None:
        ordered = sorted(
            (node for root in roots for node in root.walk()), key=lambda n: n.doc_order
        )
        plot_ids: dict[tuple[Optional[int], int], int] = {}

        for section in ordered:
            section_id = self.section_ids.get(section.doc_order)
            chapter = section.ancestor_of_kind("chapter")
            chapter_id = self.section_ids.get(chapter.doc_order) if chapter else None

            if section.kind == "plot":
                match = _PLOT_NUMBER_RE.match(section.title)
                number = int(match.group(1)) if match else section.ordinal + 1
                cursor = self.conn.execute(
                    """
                    INSERT INTO module_plots
                        (module_id, chapter_id, section_id, plot_number, title,
                         description, page)
                    VALUES (?,?,?,?,?,?,?)
                    """,
                    (
                        self.module_id, chapter_id, section_id, number,
                        section.title, section.body_md, 0,
                    ),
                )
                plot_ids[(chapter_id, number)] = cursor.lastrowid

            elif section.kind in {"event", "event_note"}:
                # Events reference the plot they advance when the text names one.
                # Several may be named; the first is the one the beat belongs to.
                plot_id = None
                reference = _PLOT_REF_RE.search(section.body_md or "")
                if reference:
                    plot_id = plot_ids.get((chapter_id, int(reference.group(1))))
                self.conn.execute(
                    """
                    INSERT INTO module_events
                        (module_id, chapter_id, section_id, plot_id, ordinal,
                         time_label, time_minutes, description, page)
                    VALUES (?,?,?,?,?,?,?,?,?)
                    """,
                    (
                        self.module_id, chapter_id, section_id, plot_id,
                        section.doc_order, section.title,
                        time_to_minutes(section.title), section.body_md, 0,
                    ),
                )

    # ── NPCs ─────────────────────────────────────────────────────────────────

    def write_npcs(self, actors: list[dict]) -> None:
        for actor in actors:
            name = actor.get("name", "")
            slug = slugify(name)
            profile = _profile_row(actor)
            stats = profile["stats"]
            # "Creature" actors cover collective and bestiary entries; so do
            # plural names that carry no career.
            has_career = any(i.get("type") == "career" for i in actor.get("items", []))
            is_group = 1 if actor.get("type") == "creature" or (
                re.search(r"s$|\band\b", name, re.IGNORECASE) and not has_career
            ) else 0

            cursor = self.conn.execute(
                """
                INSERT INTO module_npcs
                    (module_id, section_id, slug, name, title, faction,
                     description, is_group, page)
                VALUES (?,?,?,?,?,?,?,?,?)
                """,
                (
                    self.module_id, None, slug, name, _npc_title(actor),
                    # Foundry has no concept of the book's NPC groupings, so
                    # faction is left for a campaign to fill in.
                    "", _npc_description(actor), is_group, 0,
                ),
            )
            npc_id = cursor.lastrowid
            self.npc_ids[actor["_id"]] = npc_id

            self.conn.execute(
                """
                INSERT INTO module_npc_profiles
                    (npc_id, label, m, ws, bs, s, t, i, ag, dex, intl, wp, fel, w,
                     skills_json, talents_json, traits_json, trappings_json,
                     spells_json, page)
                VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                """,
                (
                    npc_id, _detail(actor, "species").title(),
                    stats.get("m"), stats.get("ws"), stats.get("bs"), stats.get("s"),
                    stats.get("t"), stats.get("i"), stats.get("ag"), stats.get("dex"),
                    stats.get("intl"), stats.get("wp"), stats.get("fel"), stats.get("w"),
                    json.dumps(profile["skills"]), json.dumps(profile["talents"]),
                    json.dumps(profile["traits"]), json.dumps(profile["trappings"]),
                    json.dumps(profile["spells"]), 0,
                ),
            )

    def write_appearances(self, journals: list[dict]) -> int:
        """Link NPCs to the pages that mention them.

        The book's prose carries an explicit ``@UUID`` link at every point an
        actor is invoked, so the NPC-to-scene graph is read directly rather than
        guessed from name matching.
        """
        written = 0
        for journal in journals:
            for page in journal["pages"]:
                target = self.section_by_source.get(page["_id"])
                if not target:
                    continue
                section_id, chapter_id = target
                seen: set[str] = set()
                for reference, label in _UUID_RE.findall(page["html"]):
                    actor_id = reference.split(".")[-1]
                    npc_id = self.npc_ids.get(actor_id)
                    if npc_id is None or actor_id in seen:
                        continue
                    seen.add(actor_id)
                    self.conn.execute(
                        """
                        INSERT OR IGNORE INTO module_npc_appearances
                            (npc_id, section_id, chapter_id, role, notes)
                        VALUES (?,?,?,?,?)
                        """,
                        (npc_id, section_id, chapter_id, "", label or ""),
                    )
                    written += 1
        self._backfill_npc_sections()
        return written

    def _backfill_npc_sections(self) -> None:
        """Give each NPC a home section: the first page that references it."""
        self.conn.execute(
            """
            UPDATE module_npcs SET section_id = (
                SELECT a.section_id FROM module_npc_appearances a
                WHERE a.npc_id = module_npcs.id ORDER BY a.section_id LIMIT 1
            )
            WHERE module_id = ? AND section_id IS NULL
            """,
            (self.module_id,),
        )

    # ── assets and tables ────────────────────────────────────────────────────

    def write_assets(self, assets: list[Asset], repo_root: str) -> None:
        for asset in assets:
            # Stored relative to the repository root so the database can be built
            # on one machine and served from another.
            relative = os.path.relpath(os.path.abspath(asset.path), repo_root)
            cursor = self.conn.execute(
                """
                INSERT INTO module_assets
                    (module_id, section_id, chapter_id, kind, path, caption, page,
                     bbox_json, width, height, sha256)
                VALUES (?,?,?,?,?,?,?,?,?,?,?)
                """,
                (
                    self.module_id, None, None, asset.kind, relative, asset.caption,
                    0, "", asset.width, asset.height, asset.sha256,
                ),
            )
            self.asset_ids[asset.source] = cursor.lastrowid

    def link_portraits(self, actors: list[dict]) -> int:
        """Point each NPC at its token art, and each portrait at its NPC."""
        linked = 0
        for actor in actors:
            npc_id = self.npc_ids.get(actor["_id"])
            asset_id = self.asset_ids.get(actor.get("img") or "")
            if npc_id is None or asset_id is None:
                continue
            self.conn.execute(
                "UPDATE module_npcs SET portrait_id = ? WHERE id = ?", (asset_id, npc_id)
            )
            self.conn.execute(
                "UPDATE module_assets SET npc_id = ?, caption = ? WHERE id = ?",
                (npc_id, actor.get("name", ""), asset_id),
            )
            linked += 1
        return linked

    def write_tables(self, tables: list[dict]) -> None:
        for table in tables:
            rows = [
                [_format_range(result.get("range") or []), _strip_tags(result.get("text", ""))]
                for result in table.get("results", [])
            ]
            self.conn.execute(
                """
                INSERT INTO module_tables
                    (module_id, section_id, chapter_id, title, kind,
                     columns_json, rows_json, page)
                VALUES (?,?,?,?,?,?,?,?)
                """,
                (
                    self.module_id, None, None, table.get("name", ""), "roll",
                    json.dumps(["Roll", "Result"]), json.dumps(rows), 0,
                ),
            )

    # ── search index ─────────────────────────────────────────────────────────

    def build_search_index(self, roots: list[Section], actors: list[dict]) -> None:
        if not module_schema.has_fts5(self.conn):
            return
        self.conn.execute(
            "DELETE FROM module_search WHERE module_id = ?", (self.module_id,)
        )
        for section in (node for root in roots for node in root.walk()):
            if not section.body_md:
                continue
            self.conn.execute(
                """
                INSERT INTO module_search
                    (title, body, kind, module_id, section_id, npc_id, page)
                VALUES (?,?,?,?,?,?,?)
                """,
                (
                    section.title, _plain_text(section.body_md), section.kind,
                    self.module_id, self.section_ids.get(section.doc_order), None, 0,
                ),
            )
        for actor in actors:
            npc_id = self.npc_ids.get(actor["_id"])
            profile = _profile_row(actor)
            body = [_npc_description(actor)]
            for label in ("skills", "talents", "traits", "trappings"):
                entries = profile[label]
                if entries:
                    body.append(f"{label.title()}: " + ", ".join(e["name"] for e in entries))
            section_id = self.conn.execute(
                "SELECT section_id FROM module_npcs WHERE id = ?", (npc_id,)
            ).fetchone()
            self.conn.execute(
                """
                INSERT INTO module_search
                    (title, body, kind, module_id, section_id, npc_id, page)
                VALUES (?,?,?,?,?,?,?)
                """,
                (
                    actor.get("name", ""), "\n".join(p for p in body if p), "npc",
                    self.module_id, section_id[0] if section_id else None, npc_id, 0,
                ),
            )


def _format_range(bounds: list) -> str:
    if not bounds:
        return ""
    low = bounds[0]
    high = bounds[1] if len(bounds) > 1 else low
    return str(low) if low == high else f"{low}-{high}"


# ── orchestration ────────────────────────────────────────────────────────────


def ingest(
    export_path: str,
    module_dir: str,
    db_path: str,
    slug: str,
    title: str,
    image_dir: str,
) -> dict:
    with open(export_path, encoding="utf-8") as handle:
        data = json.load(handle)

    journals = data.get("journals", [])
    actors = data.get("actors", [])
    source = data.get("module", {})
    roots = build_sections(journals)
    assets = collect_assets(
        module_dir, data.get("assets", []), image_dir, source.get("id", ""),
        data.get("scenes", []),
    )

    conn = sqlite3.connect(db_path)
    conn.execute("PRAGMA foreign_keys = ON")
    module_schema.init_module_schema(conn)

    # games/wfrp/extract/foundry_module.py -> repository root
    repo_root = os.path.abspath(
        os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "..")
    )

    # Replacing a module cascades away its old content but leaves campaign state,
    # which references module id and is re-linked on the next run.
    conn.execute("DELETE FROM modules WHERE slug = ?", (slug,))
    cursor = conn.execute(
        """
        INSERT INTO modules
            (slug, title, description, system, source_file, source_sha256,
             page_count, extracted_at, extractor_version, theme_json)
        VALUES (?,?,?,?,?,?,?,?,?,?)
        """,
        (
            slug, title or source.get("title", slug),
            _strip_tags(source.get("description", "")), "WFRP 4E",
            f"{source.get('id', '')}@{source.get('version', '')}",
            file_sha256(export_path), 0,
            datetime.now(timezone.utc).isoformat(timespec="seconds"),
            EXTRACTOR_VERSION, "",
        ),
    )
    module_id = cursor.lastrowid

    writer = Ingestor(conn, module_id)
    writer.write_sections(roots)
    writer.write_plots_and_events(roots)
    writer.write_npcs(actors)
    writer.write_assets(assets, repo_root)
    writer.link_portraits(actors)
    writer.write_appearances(journals)
    writer.write_tables(data.get("tables", []))
    map_keys = apply_map_keys(conn, module_id, slug)
    writer.build_search_index(roots, actors)

    cover = conn.execute(
        "SELECT id FROM module_assets WHERE module_id = ? AND kind = 'map'"
        " ORDER BY id LIMIT 1", (module_id,)
    ).fetchone()
    if cover:
        conn.execute(
            "UPDATE modules SET cover_asset_id = ? WHERE id = ?", (cover[0], module_id)
        )

    conn.commit()
    counts = {
        table: conn.execute(
            f"SELECT COUNT(*) FROM {table} WHERE module_id = ?", (module_id,)
        ).fetchone()[0]
        for table in ("module_sections", "module_plots", "module_events",
                      "module_npcs", "module_assets", "module_tables")
    }
    counts["module_npc_profiles"] = conn.execute(
        "SELECT COUNT(*) FROM module_npc_profiles p JOIN module_npcs n ON n.id = p.npc_id"
        " WHERE n.module_id = ?", (module_id,)
    ).fetchone()[0]
    counts["module_npc_appearances"] = conn.execute(
        "SELECT COUNT(*) FROM module_npc_appearances a JOIN module_npcs n ON n.id = a.npc_id"
        " WHERE n.module_id = ?", (module_id,)
    ).fetchone()[0]
    counts["module_map_keys"] = map_keys
    conn.close()
    return counts


def main(argv: Optional[list[str]] = None) -> int:
    from .. import db as wfrp_db

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("export", help="JSON produced by foundry_export.cjs")
    parser.add_argument("--module-dir", required=True,
                        help="Foundry module directory, for its artwork")
    parser.add_argument("--slug", required=True, help="Stable module identifier")
    parser.add_argument("--title", default="", help="Display title")
    parser.add_argument("--db", default="", help="Campaign database (defaults to the live one)")
    parser.add_argument("--images", default="", help="Directory for copied artwork")
    args = parser.parse_args(argv)

    db_path = args.db or wfrp_db.get_db_path()
    image_dir = args.images or os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
        "rules", "modules", args.slug, "images",
    )

    counts = ingest(args.export, args.module_dir, db_path, args.slug,
                    args.title, image_dir)
    width = max(len(name) for name in counts)
    print(f"Ingested {args.slug!r} into {db_path}")
    for name, value in counts.items():
        print(f"  {name:<{width}}  {value}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
