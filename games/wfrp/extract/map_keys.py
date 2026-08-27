"""Numbered map callouts for *Rough Nights & Hard Days*.

The maps in this book are flat raster artwork. Their KEY boxes -- the panels that
translate the numbered circles on the floorplan into room names -- are painted
into the image, so nothing about them survives in the PDF text layer: the map
pages carry only a running head and a folio.

OCR is a poor fit here. The book sets its numerals as oldstyle figures in a
display face, so ``1`` is drawn as a small-caps ``I`` and ``0`` as ``O``;
``21`` reads as ``2I`` and ``30`` as ``3O``. An OCR pass produces exactly the
kind of quietly-wrong digits that would send a Gamemaster to the wrong room.

The keys are therefore transcribed here by hand. They are a fixed property of a
published book -- roughly 140 short strings that will never change -- so
treating them as source is more honest, and more accurate, than re-deriving
them on every ingest.
"""

from __future__ import annotations

import re
import sqlite3
from dataclasses import dataclass, field

__all__ = ["MapKey", "MapKeySet", "MAP_KEY_SETS", "apply_map_keys"]


@dataclass(frozen=True)
class MapKey:
    """One numbered callout printed on a map."""

    key: str
    label: str
    detail: str = ""
    section_slug: str = ""


@dataclass(frozen=True)
class MapKeySet:
    """A KEY panel, and the map pages it applies to.

    A single key can serve more than one page: the Staatsoper is drawn as a
    two-page spread (ground floor, then first floor) with one shared key
    printed on the second of them.
    """

    module_slug: str
    title: str
    pages: tuple[int, ...]
    entries: tuple[MapKey, ...]
    captions: dict[int, str] = field(default_factory=dict)


def _rooms(
    first: int,
    last: int,
    label: str,
    occupants: dict[int, str],
) -> list[MapKey]:
    """Expand a banded key line such as ``1-10 Double Rooms``.

    The Three Feathers key collapses its guest rooms into two ranges, but the
    circles on the floorplan are numbered individually and the SLEEPING
    ARRANGEMENTS panel assigns specific guests to specific numbers. Storing the
    band verbatim would make "who is in room 19?" unanswerable, so each number
    is expanded into its own row.
    """
    out = []
    for number in range(first, last + 1):
        occupant = occupants.get(number, "")
        out.append(
            MapKey(
                str(number),
                label,
                f"Sleeping arrangements: {occupant}" if occupant else "",
            )
        )
    return out


# ── The Three Feathers, p.12 ────────────────────────────────────────────────
# The key bands the guest rooms; the SLEEPING ARRANGEMENTS panel beside the
# floorplan assigns named guests to individual numbers.
_THREE_FEATHERS_OCCUPANTS = {
    1: "The Gravin",
    2: "Gravin's Maids",
    3: "Rechtschandler",
    4: "Bruno Franke",
    6: "Gravin's Guards",
    9: "The 'Morrians'",
    10: "The 'Scholars'",
    11: "The 'Schmidts'",
    13: "'Seedling'",
    19: "Ursula Kopfgeld",
}

_THREE_FEATHERS = MapKeySet(
    module_slug="rough-nights-and-hard-days",
    title="The Three Feathers",
    pages=(12,),
    entries=tuple(
        _rooms(1, 10, "Double Room", _THREE_FEATHERS_OCCUPANTS)
        + _rooms(11, 20, "Single Room", _THREE_FEATHERS_OCCUPANTS)
        + [
            MapKey("21", "Hall"),
            MapKey("22", "Storeroom"),
            MapKey("23", "Taproom"),
            MapKey("24", "Dormitory",
                   "Sleeping arrangements: Glimbrin & the Gravin's Servants"),
            MapKey("25", "Kitchens"),
            MapKey("26", "Staff"),
            MapKey("27", "Landlord"),
            MapKey("28", "Stables", section_slug="stables-and-smithy"),
            MapKey("29", "Smithy", section_slug="stables-and-smithy"),
            MapKey("30", "Outhouse", section_slug="outhouse"),
            MapKey("31", "Landing Stage", section_slug="landing-stage"),
        ]
    ),
)

# ── The Courthouse, p.25 ────────────────────────────────────────────────────
_COURTHOUSE = MapKeySet(
    module_slug="rough-nights-and-hard-days",
    title="The Courthouse",
    pages=(25,),
    entries=(
        MapKey("1", "Lobby"),
        MapKey("2", "Porter's Room"),
        MapKey("3", "Clerk's Office"),
        MapKey("4", "Watch Station"),
        MapKey("5", "Judge's Chamber"),
        MapKey("6", "Courtroom"),
        MapKey("7", "Cells"),
        MapKey("8", "Corridor"),
        MapKey("9", "Passage"),
        MapKey("10", "The Yard"),
        MapKey("11", "Gallows Pole"),
        MapKey("12", "Gallery"),
        MapKey("13", "Law Library"),
        MapKey("14", "Chapel to Verena"),
        MapKey("15", "Guild Offices"),
        MapKey("16", "Lounge"),
    ),
)

# ── The Arena, p.27 ─────────────────────────────────────────────────────────
_ARENA = MapKeySet(
    module_slug="rough-nights-and-hard-days",
    title="The Arena",
    pages=(27,),
    entries=(
        MapKey("1", "Makeshift Arena"),
        MapKey("2", "Ambosstein Pavilion"),
        MapKey("3", "Dammenblatz Pavilion"),
        MapKey("4", "Grandstand"),
        MapKey("5", "Box"),
        MapKey("6", "Courthouse"),
    ),
)

# ── Staatsoper Theatre, pp.39-40 ────────────────────────────────────────────
# Drawn as a spread: ground floor on p.39, first floor on p.40. The single KEY
# is printed on p.40 and covers both. The p.39 half carries no bookmark, so the
# extractor files it as untitled art; `apply_map_keys` promotes it.
_STAATSOPER = MapKeySet(
    module_slug="rough-nights-and-hard-days",
    title="Staatsoper Theatre",
    pages=(39, 40),
    captions={
        39: "Staatsoper Theatre Map (Ground Floor)",
        40: "Staatsoper Theatre Map (First Floor)",
    },
    entries=(
        MapKey("1", "Ladies' Door"),
        MapKey("2", "Lords' Door"),
        MapKey("3", "Main Staircase"),
        MapKey("4", "Ladies' Chamber"),
        MapKey("5", "Lords' Chamber"),
        MapKey("6", "Box Office and Cloakroom"),
        MapKey("7", "Lobby"),
        MapKey("8", "Ladies' Stair"),
        MapKey("9", "Lords' Stair"),
        MapKey("10", "Passage"),
        MapKey("11", "Chorus Dressing Room (Male)"),
        MapKey("12", "Chorus Dressing Room (Female)"),
        MapKey("13", "Dressing Room"),
        MapKey("14", "Green Room"),
        MapKey("15", "Stage Manager's Office"),
        MapKey("16", "Backstage"),
        MapKey("17", "Stalls"),
        MapKey("18", "Orchestra Pit"),
        MapKey("19", "Stage"),
        MapKey("20", "Scenery Staging Area"),
        MapKey("21", "Props Storage"),
        MapKey("22", "Concierge's Office"),
        MapKey("23", "Props Manager's Office"),
        MapKey("24", "Costume Storage"),
        MapKey("25", "Seamstresses"),
        MapKey("26", "Carpentry and Scenery"),
        MapKey("27", "General Storage"),
        MapKey("28", "Box"),
        MapKey("29", "Noble Box"),
        MapKey("30", "Royal Box"),
        MapKey("31", "Box Lounge"),
        MapKey("32", "Ducal Antechamber"),
        MapKey("33", "Left Balcony Seats"),
        MapKey("34", "Central Balcony Seats"),
        MapKey("35", "Right Balcony Seats"),
        MapKey("36", "Gallery"),
        MapKey("37", "Balcony Bar"),
        MapKey("38", "Ladies' Lounge"),
        MapKey("39", "Lords' Lounge"),
    ),
)

# ── Castle Grauenberg, p.57 ─────────────────────────────────────────────────
# The artwork titles this "Castle Grauenberg"; the PDF bookmark spells it
# "Grauenburg". The body text agrees with the artwork ("Schloss Grauenberg").
_GRAUENBERG = MapKeySet(
    module_slug="rough-nights-and-hard-days",
    title="Castle Grauenberg",
    pages=(57,),
    entries=(
        MapKey("1", "Gatehouse and State Army Barracks", section_slug="gatehouse"),
        MapKey("2", "Courtyard"),
        MapKey("3", "Garden", section_slug="the-formal-gardens"),
        MapKey("4", "Blacksmiths", section_slug="stables-coach-house-and-smithy"),
        MapKey("5", "Coach House", section_slug="stables-coach-house-and-smithy"),
        MapKey("6", "Stables", section_slug="stables-coach-house-and-smithy"),
        MapKey("7", "Kennels and Mews", section_slug="kennels-and-mews"),
        MapKey("8", "Entry Hall"),
        MapKey("9", "Great Hall"),
        MapKey("10", "Kitchens"),
        MapKey("11", "Storerooms"),
        MapKey("12", "Servants' Tower"),
        MapKey("13", "Saponatheim Apartments"),
        MapKey("14", "Saponatheim Chapel"),
        MapKey("15", "Siegfried Tower", "Leads to the extra Guest Chambers"),
        MapKey("16", "Solar Tower", section_slug="solar-tower"),
        MapKey("17", "Geschloss Tower", "Leads to the extra Guest Chambers"),
        MapKey("18", "Guest Chambers"),
        MapKey("19", "Ambosstein Guest Chambers"),
        MapKey("20", "Dining Room"),
        MapKey("21", "Entertainers' Quarters"),
        MapKey("22", "Closed, Crumbling Wing"),
    ),
)

# ── Niederstadt Haus, p.72 ──────────────────────────────────────────────────
_NIEDERSTADT = MapKeySet(
    module_slug="rough-nights-and-hard-days",
    title="Niederstadt Haus",
    pages=(72,),
    entries=(
        MapKey("1", "Portico"),
        MapKey("2", "Carriage House"),
        MapKey("3", "Stable"),
        MapKey("4", "Kennels"),
        MapKey("5", "Storeroom"),
        MapKey("6", "Garden"),
        MapKey("7", "Yard"),
        MapKey("8", "Well"),
        MapKey("9", "Vestibule"),
        MapKey("10", "Porter's Office and Cloakroom"),
        MapKey("11", "Gallery"),
        MapKey("12", "Powder Room"),
        MapKey("13", "Reception Room"),
        MapKey("14", "Dining Room"),
        MapKey("15", "Kitchen"),
        MapKey("16", "Larder"),
        MapKey("17", "Servants' Passage"),
        MapKey("18", "Landing"),
        MapKey("19", "Master Bedroom"),
        MapKey("20", "Guest Suite"),
        MapKey("21", "Dressing Room"),
        MapKey("22", "Servant Room"),
        MapKey("23", "Linen Store"),
    ),
)

# ── Gamemaster's Campaign Map, p.7 ──────────────────────────────────────────
# Not a floorplan: the numbers mark the five adventure sites in campaign order.
_CAMPAIGN = MapKeySet(
    module_slug="rough-nights-and-hard-days",
    title="Gamemaster's Campaign Map",
    pages=(7,),
    entries=(
        MapKey("1", "Three Feathers", "Adventure 1: A Rough Night at the Three Feathers",
               section_slug="a-rough-night-at-the-three-feathers"),
        MapKey("2", "Kemperbad", "Adventure 2: A Day at the Trials",
               section_slug="a-day-at-the-trials"),
        MapKey("3", "Nuln", "Adventure 3: A Night at the Opera",
               section_slug="a-night-at-the-opera"),
        MapKey("4", "Castle Grauenberg", "Adventure 4: Nastassia's Wedding",
               section_slug="nastassia-s-wedding"),
        MapKey("5", "Ubersreik", "Adventure 5: Lord of Ubersreik",
               section_slug="lord-of-ubersreik"),
    ),
)


MAP_KEY_SETS: tuple[MapKeySet, ...] = (
    _CAMPAIGN,
    _THREE_FEATHERS,
    _COURTHOUSE,
    _ARENA,
    _STAATSOPER,
    _GRAUENBERG,
    _NIEDERSTADT,
)


def _normalise(text: str) -> str:
    """Fold a heading or key label to a comparable form."""
    text = text.lower().replace("\u2019", "'").replace("\u2013", "-")
    text = re.sub(r"\b(the|and|a)\b", " ", text)
    return re.sub(r"[^a-z0-9]+", " ", text).strip()


def _resolve_section(
    entry: MapKey,
    by_slug: dict[str, list[tuple[int, int | None]]],
    candidates: list[tuple[str, int]],
    chapter_id: int | None,
) -> int | None:
    """Link a callout to the section that describes it, when one exists.

    Room sections in this book are coarse -- "Ground Floor" covers a dozen
    numbered rooms -- so most callouts have no counterpart and are left
    unlinked rather than forced onto a bad match.
    """
    if entry.section_slug:
        rows = by_slug.get(entry.section_slug)
        if not rows:
            return None
        # Slugs are only unique within a chapter: both the Three Feathers and
        # Castle Grauenberg have a "Landing Stage". Prefer the one belonging to
        # the same chapter as the map.
        for section_id, section_chapter in rows:
            if chapter_id is not None and section_chapter == chapter_id:
                return section_id
        return rows[0][0]

    target = _normalise(entry.label)
    if not target:
        return None
    for title, section_id in candidates:
        if _normalise(title) == target:
            return section_id
    return None


def apply_map_keys(
    conn: sqlite3.Connection,
    module_id: int,
    module_slug: str,
) -> int:
    """Populate ``module_map_keys`` for a freshly ingested module.

    Also promotes any map page that the outline failed to caption -- the
    Staatsoper ground floor is drawn without its own bookmark, so it arrives
    classified as untitled art.
    """
    sets = [s for s in MAP_KEY_SETS if s.module_slug == module_slug]
    if not sets:
        return 0

    by_slug: dict[str, list[tuple[int, int | None]]] = {}
    for section_id, slug, section_chapter in conn.execute(
        "SELECT id, slug, chapter_id FROM module_sections"
        " WHERE module_id = ? ORDER BY id", (module_id,)
    ):
        by_slug.setdefault(slug, []).append((section_id, section_chapter))

    written = 0
    for key_set in sets:
        for page in key_set.pages:
            row = conn.execute(
                "SELECT id, chapter_id FROM module_assets"
                " WHERE module_id = ? AND page = ? AND kind IN ('map', 'art')"
                " ORDER BY CASE kind WHEN 'map' THEN 0 ELSE 1 END, id LIMIT 1",
                (module_id, page),
            ).fetchone()
            if row is None:
                continue
            asset_id, chapter_id = row[0], row[1]

            caption = key_set.captions.get(page)
            if caption:
                conn.execute(
                    "UPDATE module_assets SET kind = 'map', caption = ? WHERE id = ?",
                    (caption, asset_id),
                )
            else:
                conn.execute(
                    "UPDATE module_assets SET kind = 'map' WHERE id = ?", (asset_id,)
                )

            candidates: list[tuple[str, int]] = []
            if chapter_id is not None:
                # Only ever match names within the map's own chapter. Room names
                # like "Main Building" and "Landing Stage" recur across
                # adventures, so a module-wide search would mislink them.
                candidates = [
                    (title, section_id)
                    for section_id, title in conn.execute(
                        "SELECT id, title FROM module_sections"
                        " WHERE module_id = ? AND kind IN ('room', 'location')"
                        "   AND chapter_id = ?",
                        (module_id, chapter_id),
                    )
                ]

            conn.execute("DELETE FROM module_map_keys WHERE asset_id = ?", (asset_id,))
            for entry in key_set.entries:
                conn.execute(
                    """
                    INSERT INTO module_map_keys
                        (asset_id, key_label, label, detail, section_id)
                    VALUES (?,?,?,?,?)
                    """,
                    (
                        asset_id, entry.key, entry.label, entry.detail,
                        _resolve_section(entry, by_slug, candidates, chapter_id),
                    ),
                )
                written += 1
    return written
