"""Loading a gang book that was transcribed by hand rather than parsed.

The core rulebook is machine-extracted: its prose and its two-column tables
survive geometry well enough that a parser is the honest tool. A gang book is
not like that. It is almost entirely datasheets and multi-column grids -- a
statline of thirteen values, a Skill Access table of fighters against six Skill
Sets, an Equipment List where the same item costs a different amount to each
gang -- and every one of those shapes is the kind that came back interleaved
or missing when it was read by column geometry.

So a gang book is read off the page images and written into a JSON file beside
the PDF, and this module is the loader for that file. It parses nothing. If a
value here is wrong it is because it was read wrong, not because a heuristic
misfired, and the fix is to look at the page again.

The file lives outside the repository because it is the book's text. Without
it the gang tables are simply empty, and ``necromunda_fighter`` says the gang
is not installed rather than inventing a statline.
"""
from __future__ import annotations

import json
import pathlib
import re

GANGS_DIRNAME = "gangs"

# "Fighter (Leader, Pious)" -> ("Fighter", "Leader, Pious")
_TYPE = re.compile(r"^\s*(\w+)\s*\(([^)]*)\)\s*$")
_STAT_KEYS = ("M", "WS", "BS", "S", "T", "W", "I", "A", "Sv",
              "Ld", "Cl", "Wil", "Int")


def books_dir(pdf_path) -> pathlib.Path:
    """Where the transcriptions live: beside the manuals, outside the repo."""
    return pathlib.Path(pdf_path).parent.parent / GANGS_DIRNAME


def available(pdf_path) -> list[pathlib.Path]:
    directory = books_dir(pdf_path)
    return sorted(directory.glob("*.json")) if directory.is_dir() else []


def split_type(type_text: str) -> tuple[str, str]:
    """A printed Type into the model type and its Subtypes."""
    match = _TYPE.match(type_text or "")
    if not match:
        return (type_text or "").strip(), ""
    return match.group(1), match.group(2).strip()


def _slug(text: str) -> str:
    from .extract import sections as sections_mod
    return sections_mod.slugify(text)


def load(conn, path: pathlib.Path) -> dict:
    """Load one transcribed gang book into the database."""
    data = json.loads(path.read_text())
    meta = data["book"]
    counts = {"gangs": 0, "fighters": 0, "skill_access": 0,
              "gang_equipment": 0, "gang_weapons": 0, "gang_wargear": 0,
              "wyrd_powers": 0}

    # The core ingest clears its own book by slug, so a gang book loaded on a
    # previous run is still there. Replace it rather than collide with it.
    from . import rules_schema
    rules_schema.reset_rulebook(conn, meta["slug"])

    book_id = conn.execute(
        "INSERT INTO rulebooks (slug, title, system, edition, source_file,"
        " page_count, page_offset, extracted_at, extractor_version)"
        " VALUES (?,?,?,?,?,?,?,?,?)",
        (meta["slug"], meta["title"], "Necromunda Skirmish",
         meta.get("edition", ""), path.name, meta.get("page_count", 0),
         meta.get("page_offset", 0), "", "read-by-eye")).lastrowid

    offset = meta.get("page_offset", 0)
    sets = data.get("skill_sets", [])

    for gang in data.get("gangs", []):
        gang_id = conn.execute(
            "INSERT INTO rule_gangs (rulebook_id, slug, name,"
            " special_rules_json, page) VALUES (?,?,?,?,?)",
            (book_id, gang["slug"], gang["name"],
             json.dumps(gang.get("special_rules", [])),
             gang.get("page", 0) + offset)).lastrowid
        counts["gangs"] += 1

        for fighter in gang.get("fighters", []):
            stats = fighter["stats"]
            model_type, subtypes = split_type(fighter.get("type", ""))
            conn.execute(
                "INSERT INTO rule_fighters (rulebook_id, gang_id, slug, name,"
                " cost, type_text, model_type, subtypes, m_text, ws_text,"
                " bs_text, s_text, t_text, w_text, i_text, a_text, sv_text,"
                " ld_text, cl_text, wil_text, int_text, starting_xp,"
                " skills_text, equipment_text, options_json, page)"
                " VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (book_id, gang_id, _slug(fighter["name"]), fighter["name"],
                 fighter.get("cost"), fighter.get("type", ""),
                 model_type, subtypes,
                 *[stats.get(k, "") for k in _STAT_KEYS],
                 fighter.get("starting_xp"), fighter.get("skills", ""),
                 fighter.get("equipment", ""),
                 json.dumps(fighter.get("options", [])),
                 fighter.get("page", 0) + offset))
            counts["fighters"] += 1

        page = gang.get("skill_access_page", 0) + offset
        for fighter, row in gang.get("skill_access", {}).items():
            for skill_set, access in zip(sets, row):
                conn.execute(
                    "INSERT INTO rule_skill_access (rulebook_id, gang_id,"
                    " fighter, skill_set, access, page) VALUES (?,?,?,?,?,?)",
                    (book_id, gang_id, fighter, skill_set,
                     "none" if access.strip() in ("-", "") else access.lower(),
                     page))
                counts["skill_access"] += 1

        for listing in gang.get("equipment_lists", []):
            for category, items in listing["sections"].items():
                for item in items:
                    conn.execute(
                        "INSERT INTO rule_gang_equipment (rulebook_id, gang_id,"
                        " list_name, category, item, slug, cost_text,"
                        " restriction, starred, page)"
                        " VALUES (?,?,?,?,?,?,?,?,?,?)",
                        (book_id, gang_id, listing["name"], category,
                         item["item"], _slug(item["item"]), item["cost"],
                         item.get("restriction", ""),
                         int(item.get("starred", False)),
                         listing.get("page", 0) + offset))
                    counts["gang_equipment"] += 1

        for weapon in gang.get("weapons", []):
            traits = weapon.get("traits", "")
            conn.execute(
                "INSERT INTO rule_weapons (rulebook_id, slug, name,"
                " weapon_class, category, parent_slug, is_variant, sr_text,"
                " lr_text, str_text, ap_text, lethality_text, creds_text,"
                " tp_text, traits, traits_json, cells_json, needs_review, page)"
                " VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,0,?)",
                (book_id, _slug(weapon["name"]), weapon["name"],
                 "close_combat" if "Melee" in traits else "ranged",
                 gang["name"], _slug(weapon.get("parent", "")),
                 int(bool(weapon.get("parent"))),
                 weapon.get("sr", ""), weapon.get("lr", ""),
                 weapon.get("str", ""), weapon.get("ap", ""),
                 weapon.get("lethality", ""), weapon.get("creds", ""),
                 weapon.get("tp", ""), traits,
                 json.dumps([t.strip() for t in traits.split(",") if t.strip()]),
                 json.dumps(weapon.get("aliases", [])),
                 weapon.get("page", 0) + offset))
            counts["gang_weapons"] += 1

        for item in gang.get("wargear", []):
            conn.execute(
                "INSERT INTO rule_equipment (rulebook_id, slug, name, category,"
                " description, page) VALUES (?,?,?,?,?,?)",
                (book_id, _slug(item["name"]), item["name"],
                 item.get("category", ""), item.get("text", ""),
                 item.get("page", 0) + offset))
            counts["gang_wargear"] += 1

        powers = gang.get("wyrd_powers")
        if powers:
            table_id = conn.execute(
                "INSERT INTO rule_tables (rulebook_id, slug, title, kind, dice,"
                " columns_json, notes, page) VALUES (?,?,?,?,?,?,?,?)",
                (book_id, _slug(powers["name"]), powers["name"], "reference",
                 powers.get("dice", "D6"), json.dumps(["D6", "Wyrd Power"]),
                 powers.get("intro", ""),
                 powers.get("page", 0) + offset)).lastrowid
            for ordinal, power in enumerate(powers["powers"]):
                roll = power["roll"]
                conn.execute(
                    "INSERT INTO rule_table_rows (table_id, ordinal, roll_min,"
                    " roll_max, roll_label, result, detail, cells_json)"
                    " VALUES (?,?,?,?,?,?,?,?)",
                    (table_id, ordinal, roll, roll, str(roll),
                     f"{power['name']} ({power['cost']}): {power['text']}",
                     power["cost"],
                     json.dumps([str(roll), power["name"], power["text"]])))
                counts["wyrd_powers"] += 1
    return book_id, counts
