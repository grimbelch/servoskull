"""Walking a player through Battlefield Set-Up, one stage at a time.

Setting up a Necromunda battle is six stages across four pages, and the stages
feed each other: the Crew table decides how both players pick their starting
crew and whether either gets Reinforcements, and the Deployment table decides
where the zones are. A player reading it cold flips back and forth, and the
ordering traps are easy to miss -- Pitch Black is rolled *after* the terrain is
down but *before* anyone chooses a deployment zone, so rolling it at the end
means the battlefield was built under the wrong visibility.

So the walkthrough holds the player's place and carries the earlier results
forward. Asked for the crew stage it does not recite all three selection
methods; it names the one the Crew table actually rolled and reads out that
method alone.

Every word of rules text comes from the database, which came from the book. The
only sentences composed here are the instructions telling the player what to do
at this moment, and the citation that lets them check the page.
"""
from __future__ import annotations

import json
import re

from core import config
from . import db as necro_db
from . import dice
from .rules_tools import current_rulebook, printed_page

_STATE_FILE = "necromunda_setup.json"

# The four tables a challenge is generated on, in the order the book prints
# them, and who rolls each. The book is specific and the three differ: the
# challenger rolls for Deployment and the Objective, the challenged player
# rolls for Crew, and the Side Job is rolled by EACH player, so that one comes
# back twice and the two gangs can be chasing different payouts.
_SCENARIO_TABLES = (
    ("DEPLOYMENT TABLE", "the challenger", False),
    ("OBJECTIVE TABLE", "the challenger", False),
    ("SIDE JOB TABLE", "each player", True),
    ("CREW TABLE", "the challenged player", False),
)
_TABLE_NAMES = tuple(name for name, _who, _each in _SCENARIO_TABLES)

# Which selection method the Crew table named, and the section that explains it.
_METHODS = {
    "hybrid": "hybrid-selection-x-y",
    "custom": "custom-selection-x",
    "random": "random-selection-x",
}
# "Both gangs use the Hybrid (3+4) method", "the Custom (10) method".
_METHOD = re.compile(r"\b(Hybrid|Custom|Random)\s*(\([^)]*\))", re.I)
# "Reinforcements (4)" anywhere in the Crew table's result.
_REINFORCEMENTS = re.compile(r"\bReinforcements\s*\(([^)]*)\)", re.I)


# ── the stages ────────────────────────────────────────────────────────────────

STAGES = (
    {"key": "scenario", "title": "Scenario generation",
     "sections": ("scenario-generation-tables",)},
    {"key": "battlefield", "title": "The battlefield and its terrain",
     "sections": ("underhive",)},
    {"key": "pitch_black", "title": "Pitch Black", "optional": True,
     "sections": ("pitch-black",)},
    {"key": "crew", "title": "Crew selection", "sections": ()},
    {"key": "reinforcements", "title": "Reinforcements", "optional": True,
     "sections": ("reinforcements-x",)},
    {"key": "deployment", "title": "Deployment",
     "sections": ("deployment",)},
)

_INDEX = {stage["key"]: n for n, stage in enumerate(STAGES)}

# A stage whose builder opens with this does not apply to this scenario, so its
# rule is not read out -- naming it and moving on is the whole of the step.
_SKIPPED = "Not needed this battle."


# ── state ─────────────────────────────────────────────────────────────────────

def _state_path():
    return config.data_path(_STATE_FILE)


def _load() -> dict | None:
    path = _state_path()
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text())
    except (OSError, ValueError):
        return None


def _save(state: dict) -> None:
    try:
        _state_path().write_text(json.dumps(state, indent=2))
    except OSError as exc:
        print(f"[necromunda] Could not save set-up progress: {exc}")


def _clear() -> None:
    try:
        _state_path().unlink(missing_ok=True)
    except OSError:
        pass


# ── reading the book ──────────────────────────────────────────────────────────

def _section(conn, book_id: int, slug: str):
    return conn.execute(
        "SELECT title, body_md, page_start FROM rule_sections"
        " WHERE rulebook_id = ? AND slug = ? LIMIT 1",
        (book_id, slug)).fetchone()


def _roll_table(conn, book_id: int, title: str) -> dict | None:
    """Roll one of the scenario tables and return the row it landed on."""
    table = conn.execute(
        "SELECT id, title, dice, page, notes FROM rule_tables"
        " WHERE rulebook_id = ? AND title = ? LIMIT 1",
        (book_id, title)).fetchone()
    if table is None:
        return None
    value = sum(dice.d6(2)) if table["dice"].upper() == "2D6" else dice.d6(1)[0]
    row = conn.execute(
        "SELECT roll_label, result FROM rule_table_rows WHERE table_id = ?"
        " AND roll_min <= ? AND roll_max >= ? ORDER BY ordinal LIMIT 1",
        (table["id"], value, value)).fetchone()
    return {"table": table["title"], "dice": table["dice"], "roll": value,
            "page": table["page"], "notes": table["notes"],
            "result": row["result"] if row else "",
            "label": row["roll_label"] if row else ""}


# ── the walkthrough ───────────────────────────────────────────────────────────

def begin(attacker: str = "", defender: str = "") -> str:
    """Start a fresh walkthrough and roll the scenario.

    The four tables are rolled here rather than later because every stage after
    this one reads them.
    """
    conn = necro_db.connect(create=False)
    if conn is None:
        return ("The Necromunda library is not installed on this unit, so this "
                "unit cannot walk the set-up.")
    try:
        book = current_rulebook(conn)
        rolls = {}
        for title, who, per_player in _SCENARIO_TABLES:
            if per_player:
                drawn = [_roll_table(conn, book["id"], title) for _ in range(2)]
                drawn = [d for d in drawn if d is not None]
                if drawn:
                    rolls[title] = {"who": who, "each": True, "rolls": drawn}
                continue
            result = _roll_table(conn, book["id"], title)
            if result is not None:
                result.update({"who": who, "each": False})
                rolls[title] = result
        state = {"stage": 0, "rolls": rolls,
                 "attacker": attacker.strip(), "defender": defender.strip(),
                 "visibility": "", "done": []}
        _save(state)
        return _render(conn, book, state)
    finally:
        conn.close()


def advance() -> str:
    """Finish the current stage and read out the next one."""
    state = _load()
    if state is None:
        return ("No set-up is in progress. Say 'walk me through battlefield "
                "set-up' to begin one.")
    conn = necro_db.connect(create=False)
    if conn is None:
        return "The Necromunda library is not installed on this unit."
    try:
        book = current_rulebook(conn)
        key = STAGES[state["stage"]]["key"]
        if key not in state["done"]:
            state["done"].append(key)
        if state["stage"] + 1 >= len(STAGES):
            _clear()
            return (f"That is the set-up complete. {_scenario_line(state)} "
                    f"Fight well.")
        state["stage"] += 1
        _save(state)
        return _render(conn, book, state)
    finally:
        conn.close()


def current() -> str:
    """Read the current stage again, without advancing."""
    state = _load()
    if state is None:
        return ("No set-up is in progress. Say 'walk me through battlefield "
                "set-up' to begin one.")
    conn = necro_db.connect(create=False)
    if conn is None:
        return "The Necromunda library is not installed on this unit."
    try:
        return _render(conn, current_rulebook(conn), state)
    finally:
        conn.close()


def go_to(stage: str) -> str:
    """Jump to a named stage, for a player who wants to go back over one."""
    state = _load()
    if state is None:
        return ("No set-up is in progress. Say 'walk me through battlefield "
                "set-up' to begin one.")
    wanted = (stage or "").strip().lower().replace(" ", "_")
    match = next((k for k in _INDEX if k == wanted), None)
    if match is None:
        match = next((k for k in _INDEX if wanted and wanted in k), None)
    if match is None:
        named = ", ".join(s["title"] for s in STAGES)
        return f"There is no set-up stage called '{stage}'. The stages are: {named}."
    state["stage"] = _INDEX[match]
    _save(state)
    conn = necro_db.connect(create=False)
    if conn is None:
        return "The Necromunda library is not installed on this unit."
    try:
        return _render(conn, current_rulebook(conn), state)
    finally:
        conn.close()


def abandon() -> str:
    """Throw away a walkthrough in progress."""
    if _load() is None:
        return "No set-up is in progress."
    _clear()
    return "This unit has discarded the set-up in progress."


def status() -> str:
    """What the scenario is and how far the set-up has got."""
    state = _load()
    if state is None:
        return "No set-up is in progress."
    stage = STAGES[state["stage"]]
    done = len(state["done"])
    lines = [f"Battlefield set-up, stage {state['stage'] + 1} of {len(STAGES)}: "
             f"{stage['title']} ({done} done)."]
    lines.append(_scenario_line(state))
    if state.get("visibility"):
        lines.append(f"Visibility: {state['visibility']}")
    return " ".join(lines)


# ── rendering a stage ─────────────────────────────────────────────────────────

def _scenario_line(state: dict) -> str:
    """The scenario in one line: the name each table rolled."""
    parts = []
    for title in _TABLE_NAMES:
        roll = state["rolls"].get(title)
        if not roll:
            continue
        if roll.get("each"):
            each = " and ".join(f"{_headline(r['result'])} ({r['roll']})"
                                for r in roll["rolls"])
            parts.append(f"Side Jobs {each}")
        else:
            parts.append(f"{_headline(roll['result'])} ({roll['roll']})")
    return "Scenario: " + "; ".join(parts) + "." if parts else ""


def _headline(result: str) -> str:
    """A table result's name, which the book prints before the colon."""
    head = result.split(":", 1)[0].strip()
    return head if head and len(head) < 60 else result[:60].strip()


def _sides(state: dict) -> str:
    """Who is attacker and who defender, when the player has said."""
    if state.get("attacker") and state.get("defender"):
        return (f"{state['attacker']} attacks, {state['defender']} defends. ")
    return ""


def _render(conn, book, state: dict) -> str:
    stage = STAGES[state["stage"]]
    number = state["stage"] + 1
    out = [f"Stage {number} of {len(STAGES)}: {stage['title']}."]

    builder = _BUILDERS.get(stage["key"])
    built = builder(conn, book, state) if builder is not None else ""
    if built:
        out.append(built)

    for slug in (() if built.startswith(_SKIPPED) else stage["sections"]):
        row = _section(conn, book["id"], slug)
        if row is None:
            continue
        out.append(f"{row['title']} ({book['title']}, "
                   f"p{printed_page(row['page_start'], book)}):\n"
                   f"{row['body_md']}")

    tail = ("Say 'next' when that is done."
            if number < len(STAGES) else "Say 'next' to finish.")
    out.append(tail)
    return "\n\n".join(part for part in out if part)


def _build_scenario(conn, book, state: dict) -> str:
    """The four rolls, each with the page it came off."""
    lines = [_sides(state) + "This unit has rolled the challenge."]
    for title in _TABLE_NAMES:
        roll = state["rolls"].get(title)
        if roll is None:
            continue
        if roll.get("each"):
            # One Side Job per gang: the two are chasing different payouts.
            for n, one in enumerate(roll["rolls"], start=1):
                side = _gang_name(state, n)
                lines.append(
                    f"  {title} for {side}, {one['dice']} {one['roll']}: "
                    f"{one['result']} (p{printed_page(one['page'], book)})")
            continue
        lines.append(f"  {title} ({roll['who']}), {roll['dice']} "
                     f"{roll['roll']}: {roll['result']} "
                     f"(p{printed_page(roll['page'], book)})")
        if roll["notes"]:
            lines.append(f"    Note: {roll['notes']}")
    return "\n".join(lines)


def _gang_name(state: dict, index: int) -> str:
    """What to call each side, using the names the player gave if they did."""
    names = [state.get("attacker", ""), state.get("defender", "")]
    name = names[index - 1] if index <= len(names) else ""
    return name or f"gang {index}"


def _build_pitch_black(conn, book, state: dict) -> str:
    """Optional, and rolled at this point in the sequence for a reason."""
    if not state.get("visibility"):
        roll = _roll_table(conn, book["id"], "PITCH BLACK TABLE")
        if roll is not None:
            state["visibility"] = roll["result"]
            state["pitch_black_roll"] = roll["roll"]
            _save(state)
    rolled = state.get("pitch_black_roll")
    head = ("This stage is only used if both players want it. The terrain is "
            "down and no deployment zone has been chosen yet, which is when "
            "the book has it rolled.")
    if state.get("visibility"):
        head += (f"\n  PITCH BLACK TABLE, D6 {rolled}: {state['visibility']}")
    return head


def _build_crew(conn, book, state: dict) -> str:
    """Name the method the Crew table rolled, and read out that one only."""
    crew = state["rolls"].get("CREW TABLE")
    if crew is None:
        return ""
    lines = [f"The Crew table rolled {crew['roll']}: {crew['result']}"]
    match = _METHOD.search(crew["result"])
    if match is None:
        return "\n".join(lines)
    method, value = match.group(1).lower(), match.group(2)
    row = _section(conn, book["id"], _METHODS.get(method, ""))
    if row is not None:
        lines.append(f"That is {match.group(1).title()} Selection {value}. "
                     f"{row['title']} ({book['title']}, "
                     f"p{printed_page(row['page_start'], book)}):\n"
                     f"{row['body_md']}")
    return "\n\n".join(lines)


def _build_reinforcements(conn, book, state: dict) -> str:
    """Only some Crew table results give Reinforcements."""
    crew = state["rolls"].get("CREW TABLE")
    result = crew["result"] if crew else ""
    match = _REINFORCEMENTS.search(result)
    if match is None:
        return (f"{_SKIPPED} The Crew table result does not give either gang "
                "Reinforcements. The rule is on "
                f"p{printed_page(143, book)} if it is needed.")
    return f"The Crew table gives Reinforcements ({match.group(1)})."


def _build_deployment(conn, book, state: dict) -> str:
    """The zones come from the Deployment table rolled at the start."""
    roll = state["rolls"].get("DEPLOYMENT TABLE")
    if roll is None:
        return ""
    lines = [f"The Deployment table rolled {roll['roll']}: {roll['result']} "
             f"(p{printed_page(roll['page'], book)})"]
    if state.get("visibility"):
        lines.append(f"Visibility in force: {state['visibility']}")
    return "\n".join(lines)


_BUILDERS = {
    "scenario": _build_scenario,
    "pitch_black": _build_pitch_black,
    "crew": _build_crew,
    "reinforcements": _build_reinforcements,
    "deployment": _build_deployment,
}
