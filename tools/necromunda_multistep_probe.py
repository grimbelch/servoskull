"""Measure whether Omega-7 actually composes multi-step rules answers.

Every fact these questions need is in the database and reachable by one tool
call. What is NOT known is whether the model reliably strings two or three of
them together: reading a weapon's Strength as "S+1", finding the wielder's own
Strength, comparing that to a different fighter's Toughness, and only then
answering. That composition is the one part of a rules answer that is not
deterministic, and before building anything to prop it up it is worth finding
out whether it fails at all.

The expected answers below were each checked against the database by hand, so
a disagreement is a real disagreement and not two guesses.

This drives the same model and the same tools the unit uses, but it does not
go through brain.respond(): that writes conversation history, moves the eye and
can speak. Nothing here touches Omega-7's state.

Run it on the unit, where the key and the database both live:
    ./.venv/bin/python tools/necromunda_multistep_probe.py
"""
from __future__ import annotations

import json
import os
import re
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

QUESTIONS = [
    {
        "id": "wound-chain",
        "steps": 3,
        "ask": "A Goliath Forge Breaker attacks a Van Saar Prime with crucible "
               "hooks. What do I need to roll to wound?",
        "expect": [r"\b3\+"],
        "truth": "Crucible hooks are Str S+1; a Forge Breaker is S3, so Str 4 "
                 "against the Prime's T3. Strength greater than Toughness "
                 "wounds on 3+.",
    },
    {
        "id": "wound-chain-double",
        "steps": 3,
        "ask": "My Malstrain Alpha hits an Orlock Road Captain with its "
               "razor-sharp claws. What do I need to wound?",
        "expect": [r"\b2\+"],
        "truth": "Razor-sharp claws are Str S+1; the Alpha is S5, so Str 6 "
                 "against the Road Captain's T3. Twice or greater wounds on 2+.",
    },
    {
        "id": "two-facts-one-sheet",
        "steps": 2,
        "ask": "How many Wounds does a Khimerix have, and what does it need to "
               "wound a Goliath Bruiser with its talons?",
        "expect": [r"\b4\b.*\bWound", r"\b4\+"],
        "truth": "Khimerix has 4 Wounds. Talons are Str S and the Khimerix is "
                 "S4, equal to the Bruiser's T4, so it wounds on 4+.",
    },
    {
        "id": "equipment-scope",
        "steps": 2,
        "ask": "Can a Cawdor Word-Keeper buy a 'Renderizer' serrated axe?",
        "expect": [r"\bno\b|cannot|can't|not available|not on"],
        "truth": "A Word-Keeper buys from the House Cawdor Equipment List. The "
                 "Renderizer is on the House Goliath list only, so no.",
    },
    {
        "id": "sum-cost",
        "steps": 3,
        "ask": "What is the total credit cost of a Cawdor Word-Keeper equipped "
               "with a chain glaive and mesh armour?",
        "expect": [r"\b205\b"],
        "truth": "115 for the Word-Keeper, 50 for the chain glaive, 40 for the "
                 "mesh armour: 205 credits.",
    },
    {
        "id": "restriction",
        "steps": 2,
        "ask": "Can a Genestealer Cult Aberrant be given a boltgun?",
        "expect": [r"\bno\b|cannot|can't|may not"],
        "truth": "A Genestealer Cult Aberrant cannot be equipped with any "
                 "ranged weapons, so no.",
    },
    {
        "id": "table-then-effect",
        "steps": 2,
        "ask": "My Spyre Hunt Master was taken Out of Action and I rolled 66 "
               "on the hunting rig glitches. What happens?",
        "expect": [r"critical overload|killed instantly|dies"],
        "truth": "66 is Critical Overload: the Spyrer is killed instantly.",
    },
    {
        "id": "filter-across-gang",
        "steps": 2,
        "ask": "Which Ironhead Squat fighters are allowed to take weapons from "
               "the Exo Weapons section?",
        "expect": [r"exo master", r"exo-kyn"],
        "truth": "Only the Ironhead Squat Exo Master and the Exo-Kyn; every "
                 "other entry says they may not choose Exo Weapons.",
    },
    {
        "id": "ambiguous-price",
        "steps": 2,
        "ask": "In a Furnace Brutes gang, how much does it cost to add smoke "
               "grenades to a grenade launcher?",
        "expect": [r"\+?15"],
        "truth": "+15 credits for the plain grenade launcher. The assault "
                 "grenade launcher's smoke is +20, so a good answer "
                 "distinguishes them; the data does not record which parent "
                 "each sub-entry belongs to.",
        "known_data_gap": True,
    },
    {
        "id": "superlative",
        "steps": 2,
        "ask": "Across the gang books you hold, which Leader is the cheapest, "
               "and how much?",
        "expect": [r"ratling hunt leader", r"\b105\b"],
        "truth": "The Ratling Hunt Leader at 105 credits.",
    },
]


def build():
    from core import config, tools_schema
    import anthropic

    key = os.getenv("ANTHROPIC_API_KEY") or getattr(config, "ANTHROPIC_API_KEY", "")
    if not key:
        sys.exit("No ANTHROPIC_API_KEY; run this on the unit.")
    tools = [t for t in tools_schema.build_tools()
             if t["name"].startswith("necromunda_")
             or t["name"] == "roll_necromunda_dice"]
    from personalities.omega7 import brain as persona_brain
    return anthropic.Anthropic(api_key=key), tools, persona_brain.get_handlers()


SYSTEM = (
    "You are Omega-7, answering Necromunda rules questions for a player. "
    "Always look facts up with the tools rather than recalling them. Several "
    "rulebooks are held and a fact may live in any of them. Answer the whole "
    "question, including any arithmetic it needs, and state the final number "
    "or verdict plainly. Keep it brief."
)


def ask(client, tools, handlers, question, model, max_turns=8):
    messages = [{"role": "user", "content": question}]
    used = []
    for _ in range(max_turns):
        reply = client.messages.create(model=model, max_tokens=900,
                                       system=SYSTEM, tools=tools,
                                       messages=messages)
        calls = [b for b in reply.content if b.type == "tool_use"]
        messages.append({"role": "assistant", "content": reply.content})
        if not calls:
            text = "".join(b.text for b in reply.content if b.type == "text")
            return text.strip(), used
        results = []
        for call in calls:
            used.append(call.name)
            handler = handlers.get(call.name)
            try:
                out = handler(call.input) if handler else f"no handler: {call.name}"
            except Exception as exc:                       # noqa: BLE001
                out = f"tool error: {exc}"
            results.append({"type": "tool_result", "tool_use_id": call.id,
                            "content": str(out)[:6000]})
        messages.append({"role": "user", "content": results})
    return "(no final answer within turn limit)", used


def main():
    from core import config
    client, tools, handlers = build()
    model = os.getenv("PROBE_MODEL", config.CLAUDE_MODEL)
    runs = int(os.getenv("PROBE_RUNS", "3"))
    print(f"model: {model}   tools: {len(tools)}   runs per question: {runs}\n")
    report = []
    for q in QUESTIONS:
        outcomes = []
        for _ in range(runs):
            answer, used = ask(client, tools, handlers, q["ask"], model)
            ok = all(re.search(p, answer, re.I) for p in q["expect"])
            outcomes.append({"pass": ok, "answer": answer, "tools": used})
            time.sleep(1)
        passes = sum(o["pass"] for o in outcomes)
        flag = "GAP " if q.get("known_data_gap") else ""
        print(f"{flag}{q['id']:22s} {passes}/{runs}")
        for o in outcomes:
            if not o["pass"]:
                print(f"    MISS tools={o['tools']}")
                print(f"         {o['answer'][:300]}")
        report.append({"id": q["id"], "passes": passes, "runs": runs,
                       "steps": q["steps"], "truth": q["truth"],
                       "outcomes": outcomes})
    total = sum(r["passes"] for r in report)
    possible = sum(r["runs"] for r in report)
    print(f"\n{total}/{possible} correct")
    out = os.path.expanduser("~/necromunda_multistep_probe.json")
    with open(out, "w") as fh:
        json.dump(report, fh, indent=1)
    print(f"detail written to {out}")


if __name__ == "__main__":
    main()
