"""Resolving a Necromunda attack, one printed step at a time.

The core rulebook resolves an attack as a Hit roll followed by the Resolve Hits
sequence -- Wound roll, Save roll, Inflict Damage (p76-77). Each is a separate
roll with its own target number, and this keeps them separate: the skull shows
and says each step rather than announcing a single verdict, because that is how
the rule is played at the table and it is where an arbiter is actually wanted.

Every step also carries a terse one-line report. The lines are written here, not
left to the model, so that what gets said is the arithmetic -- the roll, the
target, the outcome -- rather than an invented account of the shot.
"""
from __future__ import annotations

import random

from . import dice


def wound_target(strength: int, toughness: int) -> int:
    """The D6 needed to wound, from the Strength vs Toughness table (p76).

    Order matters: the doubled and halved cases are checked before the simple
    comparisons, because a Strength of 8 against Toughness 4 is both "twice or
    greater" and "greater", and the table means the former.
    """
    if strength >= toughness * 2:
        return 2
    if strength * 2 <= toughness:
        return 6
    if strength > toughness:
        return 3
    if strength == toughness:
        return 4
    return 5


def _roll(count: int, rng) -> list[int]:
    return [rng.randint(1, 6) for _ in range(max(0, count))]


def _tally(rolls: list[int], target: int) -> int:
    return sum(1 for r in rolls if r >= target)


def resolve(shots: int = 1, ballistic_skill: int = 4, strength: int = 3,
            toughness: int = 3, ap: int = 0, save: int | None = None,
            lethality: int = 1, wounds: int = 1, weapon: str = "",
            rng: random.Random | None = None) -> dict:
    """Run the whole attack and return a step-by-step account of it."""
    rng = rng or random
    shots = max(1, int(shots))
    steps: list[dict] = []

    # 1. Hit roll -- a BS test per shot.
    hit_rolls = _roll(shots, rng)
    hits = _tally(hit_rolls, ballistic_skill)
    steps.append({
        "name": "hit", "target": ballistic_skill, "rolls": hit_rolls,
        "passed": hits,
        "line": f"{_count(hits, shots)} on {ballistic_skill}+.",
    })
    if not hits:
        steps[-1]["line"] = f"Miss. {_listing(hit_rolls)} against {ballistic_skill}+."
        return {"steps": steps, "weapon": weapon, "outcome": "missed"}

    # 2. Wound roll -- Strength against Toughness.
    need = wound_target(strength, toughness)
    wound_rolls = _roll(hits, rng)
    wounded = _tally(wound_rolls, need)
    steps.append({
        "name": "wound", "target": need, "rolls": wound_rolls, "passed": wounded,
        "line": f"Strength {strength} against Toughness {toughness} needs {need}+. "
                f"{_count(wounded, hits)}.",
    })
    if not wounded:
        steps[-1]["line"] += " No wounds."
        return {"steps": steps, "weapon": weapon, "outcome": "no wounds"}

    # 3. Save roll -- one per wound, with AP applied to the dice.
    unsaved = wounded
    if save is not None:
        save_rolls = _roll(wounded, rng)
        saved = sum(1 for r in save_rolls if r + ap >= save)
        unsaved = wounded - saved
        modifier = f"{ap:+d}" if ap else "no modifier"
        steps.append({
            "name": "save", "target": save, "rolls": save_rolls, "passed": saved,
            "line": f"Save {save}+ with {modifier}. {saved} saved, {unsaved} through.",
        })
        if not unsaved:
            steps[-1]["line"] += " No damage."
            return {"steps": steps, "weapon": weapon, "outcome": "all saved"}

    # 4. Inflict damage -- a Wound lost per hit, Injury dice when it reaches zero.
    remaining = max(0, int(wounds))
    injuries: list[dict] = []
    for _ in range(unsaved):
        remaining = max(0, remaining - 1)
        if remaining == 0:
            injuries.append(dice.injury(lethality, rng))

    if not injuries:
        steps.append({
            "name": "damage", "target": None, "rolls": [], "passed": unsaved,
            "line": f"{unsaved} wound{'s' if unsaved != 1 else ''} through. "
                    f"{remaining} left.",
        })
        return {"steps": steps, "weapon": weapon, "outcome": "wounded",
                "wounds_left": remaining}

    worst = max(injuries, key=lambda i: dice.INJURY_SEVERITY[i["most_severe"]])
    faces = ", ".join(worst["faces"])
    noun = "die" if lethality == 1 else "dice"
    line = f"Down to zero. {lethality} Injury {noun}: {faces}."
    if lethality > 1:
        line += f" Take {worst['most_severe']}."
    steps.append({
        "name": "injury", "target": None, "rolls": [], "passed": unsaved,
        "injury": worst, "line": line,
    })
    return {"steps": steps, "weapon": weapon, "outcome": worst["most_severe"],
            "wounds_left": 0}


def _count(passed: int, rolled: int) -> str:
    return f"{passed} of {rolled}"


def _listing(rolls: list[int]) -> str:
    return ", ".join(str(r) for r in rolls)


def display_steps(result: dict) -> list[dict]:
    """Turn a resolved attack into the rolls for the eye to play through.

    The first three steps are ordinary D6, so they show pips; the injury step
    shows the Injury dice's own symbols.
    """
    out: list[dict] = []
    for step in result["steps"]:
        if step["name"] == "injury":
            injury = step["injury"]
            faces = [dice.face_symbol("injury", f) for f in injury["faces"]]
            out.append({
                "kind": "injury", "faces": faces, "detail": [None] * len(faces),
                "chosen": injury["faces"].index(injury["most_severe"]),
                "result": str(len(faces)), "hold": 1.4,
            })
        elif step["rolls"]:
            rolls = step["rolls"][:6]
            out.append({
                "kind": "d6", "faces": ["pip"] * len(rolls), "detail": list(rolls),
                "chosen": -1, "result": str(step["passed"]), "hold": 1.0,
            })
    return out


def narration(result: dict) -> str:
    """The terse script: one short line per step, in order."""
    lines = [f"{step['name'].title()}. {step['line']}" for step in result["steps"]]
    return "\n".join(lines)
