"""
A rule-based Bard's Tale player: no language model in the loop.

Each call to Bot.act() looks at the screen's text (screen_text) and the game state
read from memory (memory: position, facing, party HP/SP/gold, the city map) and
returns the next Action: keys to press, a label for the eye, and any notable events
for the narrator. Two ways out to the language model:
  - None: a screen the bot doesn't understand; the agent asks the model for one turn.
  - Action.rescue: a rare, fiddly screen (Review Board, Garth's shop) the model should
    handle with the given goal until the party is back on the street.

Street goals, most urgent first:
  recruit  dead heroes below level 3 (not worth raising: retired and deleted from the
           disk), or higher ones the party can't afford to raise: at the Guild, replace
           them with newly created characters of the same role, fighters to the front
  heal     wounded (or a dead hero we can afford to raise): the temple, paying from
           the richest purse
  shop     a fighter without armour and with gold: Garth's (model-assisted)
  review   every few victories: the Review Board (model-assisted)
  explore  otherwise patrol near the Guild, kick in house doors for fights, and now
           and then visit an unexplored special building to learn what it is
"""

from __future__ import annotations

import random
import re
import time
from dataclasses import dataclass, field
from typing import Optional

from games.bardstale import navigate
from games.bardstale.memory import CLASSES, State

GUILD = (24, 15)
HOUSES = {1, 2, 3, 4}            # city map codes for ordinary houses
FIGHTERS = {"Warrior", "Paladin", "Hunter", "Monk"}
HEAL_BELOW = 0.6                 # party HP fraction that sends it to a temple
HERO_HEAL_BELOW = 0.5            # ...or any single hero below this
RUN_BELOW = 0.35                 # flee fights when party HP is under this fraction
PATROL_RADIUS = 7                # patrol streets within this many squares of the Guild
KICK_CHANCE = 0.35               # chance a patrol target is a house door to kick in
SURVEY_CHANCE = 0.25             # chance a new target is an unexplored special building
REVIEW_EVERY = 4                 # visit the Review Board after this many won fights
HEAL_GOLD_PER_HP_LEVEL = 5       # temple price: ~5 gold per missing HP per level (110 for 11 HP at 2)
RAISE_GOLD_PER_LEVEL = 900       # temple price to raise the dead: 1800 at level 2
HEAL_COOLDOWN = 180              # seconds before another temple trip (prices are estimates)
KEEP_LEVEL = 3                   # dead heroes below this level are deleted and replaced, not raised
# Skara Brae's map never changes, so these building codes (found by exploring) hold for
# every game. Others are learned as the party walks in.
KNOWN_BUILDINGS = {
    "11": "The Guild: Thou art in the Guild of Adventurers.",
    "28": "The Shoppe: Welcome to Garth's Equipment Shoppe, oh wealthy travellers!",
    "33": "Temple: Welcome, oh weary ones, to our humble temple.",
    "43": "Review Board: Wouldst thou like to be reviewed for (A)dvancement",
    "18": "Tavern: Hail, travelers! Step to the bar and I'll draw you a tankard.",
    "113": "Temple: This is the temple of the Mad God.",
    "129": "Bard's Tale: THE BARD'S TALE was designed and programmed by Michael Cranford.",
}
# Garth's basics, in the shop's (circular) list order, and what an unarmoured hero buys.
CATALOG_PRICE = {"Torch": 5, "Lamp": 15, "Broadsword": 80, "Short Sword": 30, "Dagger": 20,
                 "War Axe": 70, "Halbard": 200, "Mace": 60, "Staff": 20, "Buckler": 40,
                 "Tower Shield": 100, "Leather Armor": 70, "Chain Mail": 150, "Scale Armor": 300,
                 "Plate Armor": 700, "Robes": 40, "Helm": 50, "Leather Gloves": 80, "Gauntlets": 40,
                 "Mandolin": 130, "Harp": 130, "Flute": 130}
CATALOG = ["Torch", "Lamp", "Broadsword", "Short Sword", "Dagger", "War Axe", "Halbard", "Mace",
           "Staff", "Buckler", "Tower Shield", "Leather Armor", "Chain Mail", "Scale Armor",
           "Plate Armor", "Robes", "Helm", "Leather Gloves", "Gauntlets", "Mandolin", "Harp", "Flute"]
KIT = {"Warrior": ["Short Sword", "Leather Armor", "Buckler", "Helm", "Gauntlets"],
       "Paladin": ["Short Sword", "Leather Armor", "Buckler", "Helm", "Gauntlets"],
       "Hunter": ["Short Sword", "Leather Armor", "Buckler", "Helm", "Gauntlets"],
       "Bard": ["Short Sword", "Leather Armor", "Helm"],
       "Rogue": ["Short Sword", "Leather Armor", "Helm"]}
GUILD_DEBOUNCE = 3.0             # Guild actions hit the floppy: give an unchanged screen time
RECRUIT_NAMES = ["SKITARIUS", "VEXILLOR", "KORVAX", "DRAXUS", "MORDANT", "THULE", "ZEPHRAN",
                 "OSSIAN", "HALBRECHT", "CASSIAR", "VOLKAN", "TIBERION", "SERAPH", "ULRICH",
                 "BRONTE", "ARKHAN", "LUDMILA", "KESTREL", "ORRIN", "DAMOCLES"]
CLASS_DIGIT = {name: str(code) for code, name in CLASSES.items()}   # creation menu uses class codes
RACE_FOR = {"Warrior": "3", "Paladin": "1", "Hunter": "3", "Monk": "1", "Bard": "1",
            "Rogue": "4", "Conjurer": "2", "Magician": "2"}          # 1 Human 2 Elf 3 Dwarf 4 Hobbit
FRONT_RANK = {"Paladin": 0, "Warrior": 0, "Hunter": 0, "Monk": 0, "Bard": 1, "Rogue": 2,
              "Conjurer": 3, "Magician": 3}


@dataclass
class Action:
    keys: list[str]
    doing: str
    events: list[str] = field(default_factory=list)
    disk: Optional[str] = None
    rescue: str = ""        # set: hand this screen to the model, with this goal


def _rescue(goal: str, doing: str) -> Action:
    return Action([], doing, rescue=goal)


def _options(lines: list[str]) -> set[str]:
    """Keys offered as '(X)word' in the message box (letters and digits)."""
    return {m.group(1).upper() for l in lines for m in re.finditer(r"\(([A-Za-z0-9])\)", l)}


def _joined(lines: list[str]) -> str:
    return " ".join(l.strip() for l in lines if l.strip())


def _heal_cost(h) -> int:
    if not h.alive:
        return RAISE_GOLD_PER_LEVEL * max(1, h.level)
    return HEAL_GOLD_PER_HP_LEVEL * max(1, h.level) * (h.max_hp - h.hp)


class Bot:
    def __init__(self, knowledge: dict):
        # knowledge persists between sessions: building names by map code, danger, etc.
        self.k = knowledge
        self.k.setdefault("buildings", {})       # "code" -> "Label: first sentence inside"
        for code, desc in KNOWN_BUILDINGS.items():
            self.k["buildings"].setdefault(code, desc)
        self.k.setdefault("stats", {"fights": 0, "won": 0, "fled": 0})
        self.k.setdefault("danger", {})
        self.k.setdefault("names_used", [])
        self.k.setdefault("shop_tries", {})
        self.city: Optional[list[list[int]]] = None
        self.combat: Optional[dict] = None
        self.target: Optional[tuple[int, int]] = None
        self.target_kind = ""
        self.last_pos: Optional[tuple[int, int]] = None
        self.stuck = 0
        self.bumps = 0
        self.entering_waits = 0
        self.just_left = False
        self.last_msg = ""
        self.quiet_since = time.monotonic()
        self.pending_events: list[str] = []
        self.recruit: Optional[dict] = None       # {"name", "cls", "created", "rolls"}
        self.temple_skip: set[str] = set()
        self.temple_patient = None
        self.recruits_this_session = 0
        self.heal_after = 0.0
        self.to_delete: list[str] = []
        self.order_plan: list[tuple[int, str]] = []
        self.guild_last: tuple[str, float] = ("", 0.0)
        self.errand = ""                          # "shop"/"review" while inside on that errand
        self.shopping: dict[str, list[str]] = {}
        self.to_equip: set[str] = set()           # heroes with purchases to equip
        self.equip_tried: set = set()
        self.equip_hero = ""
        self.equip_pick = ""

    # ── entry point ────────────────────────────────────────────────────────────
    def act(self, text: dict, st: Optional[State]) -> Optional[Action]:
        lines = text["message"]
        msg = _joined(lines)
        low = msg.lower()
        label = text["location"]
        if msg != self.last_msg:
            self.last_msg, self.quiet_since = msg, time.monotonic()

        m = re.search(r"insert (\w+) disk", low)
        if m:
            disk = {"character": "character", "dungeon": "dungeon", "program": "boot",
                    "boot": "boot", "master": "boot"}.get(m.group(1))
            return Action(["SPACE"], f"Inserting {m.group(1)} disk", disk=disk) if disk else None

        if label == "The Guild" or ("thou art in the" in low and "guild" in low):
            return self._guild(text, lines, low, st)
        if "new order" in low:                  # N works in the streets too
            return self._new_order(lines, st)
        if "choose: (e,t,d,p)" in low and self.equip_hero:
            return self._equip(lines, low)
        if "equip" in low and "or 0" in low:
            return Action([self.equip_pick or "0"], "Equipping")
        if "race:" in low and "press any key" in low:
            return Action(["SPACE"], "Checking gear")

        a = self._combat(lines, low, label, st)
        if a:
            return a

        if label == "Skara Brae" and st is not None and not self._prompting(lines, low):
            if self.combat is not None:
                self._end_combat(st)
            return self._street(st)
        if label == "Skara Brae":
            return self._waiting(low)
        return self._building(label, lines, low, st)

    @staticmethod
    def _prompting(lines, low) -> bool:
        """Does the message box want an answer (a menu, a question, an input field)?"""
        return bool(_options(lines)) or bool(re.search(r"\?\s*$|:\s*<|\d>\s*$|press any key", low))

    # ── the Guild: gather the party, replace the dead ─────────────────────────
    def _guild(self, text, lines, low, st: Optional[State]) -> Optional[Action]:
        self._arrived("recruit")
        now = time.monotonic()
        if low == self.guild_last[0] and now - self.guild_last[1] < GUILD_DEBOUNCE:
            return Action([], "In the Guild")             # the disk is still working
        a = self._guild_step(text, lines, low, st)
        if a is not None and a.keys:
            self.guild_last = (low, now)
        return a

    def _guild_step(self, text, lines, low, st: Optional[State]) -> Optional[Action]:
        if "press any key" in low:
            return Action(["SPACE"], "In the Guild")
        if "drop character" in low:
            gone = self._to_retire(st)
            if not gone:
                return Action(["\x1b"], "In the Guild")
            h = gone[0]
            if h.level < KEEP_LEVEL:
                self.to_delete.append(h.name)
            self.pending_events.append(f"{h.name} is laid to rest." if h.level < KEEP_LEVEL
                                       else f"{h.name} is carried to the Guild's crypt to await resurrection.")
            return Action([str(h.slot)], f"Retiring {h.name.title()}")
        if "disk options" in low:
            if self.to_delete:
                return Action(["D"], f"Deleting {self.to_delete[0].title()}")
            if not self.recruit and st and len(st.party) < 6 and not self._to_retire(st):
                self._start_recruit(st)
            if self.recruit and not self.recruit["created"]:
                return Action(["C"], f"Creating {self.recruit['name'].title()}")
            return Action(["E"], "In the Guild")
        if "select a race" in low:
            return Action([RACE_FOR.get(self.recruit["cls"], "1") if self.recruit else "\x1b"],
                          "Choosing a race")
        if "character x" in low and "st:" in low:
            return self._choose_class(lines)
        if "enter a name" in low and "delete character" in low:
            if not self.to_delete:
                return Action(["\x1b"], "In the Guild")
            name = self.to_delete.pop(0)
            return Action([name, "RETURN"], f"Deleting {name.title()}")
        if "enter a name" in low:
            if not self.recruit:
                return Action(["\x1b"], "In the Guild")
            if "load character" in low:
                if self.recruit.get("added_tries", 0) >= 2:     # can't load it: give up on this one
                    self.recruit = None
                    return Action(["\x1b"], "In the Guild")
                self.recruit["added_tries"] = self.recruit.get("added_tries", 0) + 1
                return Action([self.recruit["name"], "RETURN"], f"Adding {self.recruit['name'].title()}")
            self.recruit["created"] = True
            return Action([self.recruit["name"], "RETURN"], f"Naming {self.recruit['name'].title()}")
        if "new order" in low:
            return self._new_order(lines, st)
        if not ("thou art in the" in low and "guild" in low):
            return self._waiting(low)

        # The Guild's main menu.
        if not text["party"]:
            return Action(["A", "*ATEAM", "RETURN"], "Gathering the party")
        if st is None:
            return Action([], "In the Guild")
        if self.recruit and self.recruit["created"]:
            if any(h.name == self.recruit["name"] for h in st.party):
                ev = f"{self.recruit['name'].title()} the {self.recruit['cls']} joins the party."
                self.recruit = None
                self.pending_events.append(ev)
            else:
                return Action(["A"], f"Adding {self.recruit['name'].title()}")
        if self._to_retire(st):
            return Action(["R"], "Retiring the fallen")
        if self.to_delete:
            return Action(["D"], "Disk options")
        if len(st.party) < 6 and (self.recruit or self._start_recruit(st)):
            return Action(["D"], f"Recruiting a {self.recruit['cls']}")
        if self._order_keys(st) and not getattr(self, "ordered", False):
            self.ordered = True
            alive = [h for h in st.party if h.alive]
            by_slot = {str(h.slot): h.name for h in alive}
            self.order_plan = [(int(k), by_slot[k]) for k in self._order_keys(st)]
            return Action(["N"], "Arranging the ranks")
        self.ordered = False
        self.just_left = True
        return Action(["E"], "Leaving the Guild")

    def _new_order(self, lines, st: Optional[State]) -> Action:
        """One hero per keypress: the game fills in the last place by itself, and a
        surplus key would land on the menu. Without a plan, keep the current order."""
        entered = {m.group(1).strip() for l in lines for m in [re.match(r"\s*\d>\s*(\S.*)", l)] if m}
        plan = self.order_plan or ([(h.slot, h.name) for h in st.party if h.alive] if st else [])
        nxt = next((slot for slot, name in plan if name not in entered), None)
        if nxt is None:
            self.order_plan = []
        return Action([str(nxt)] if nxt else [], "Arranging the ranks")

    def _start_recruit(self, st: State) -> bool:
        """Plan a new character to fill an empty place (at most 8 a session)."""
        if self.recruits_this_session >= 8:
            return False
        self.recruit = {"name": self._new_name(), "cls": self._role_needed(st), "created": False, "rolls": 0}
        self.recruits_this_session += 1
        return True

    def _choose_class(self, lines) -> Action:
        offered = {d for d in _options(lines) if d.isdigit()}
        want = CLASS_DIGIT.get(self.recruit["cls"]) if self.recruit else None
        if want in offered:
            return Action([want], f"A new {self.recruit['cls']}")
        self.recruit["rolls"] += 1
        if self.recruit["rolls"] < 8:
            return Action(["\x1b"], "Rolling again")        # abort and roll new attributes
        for fallback in ("0", "7", "5", "6", "8", "9", "3", "4"):
            if fallback in offered:
                self.recruit["cls"] = CLASSES[int(fallback)]
                return Action([fallback], f"A new {self.recruit['cls']}")
        return Action(["\x1b"], "Rolling again")

    def _role_needed(self, st: State) -> str:
        """Replace the class of a hero who died (else another fighter)."""
        alive = {h.cls for h in st.party if h.alive}
        lost = self.k.setdefault("lost_classes", [])
        for cls in list(lost):
            if cls not in alive and cls in RACE_FOR:
                lost.remove(cls)
                return cls
        fighters = sum(1 for h in st.party if h.alive and h.cls in FIGHTERS)
        return "Warrior" if fighters < 3 else "Conjurer" if "Conjurer" not in alive else "Warrior"

    def _new_name(self) -> str:
        used = set(self.k["names_used"])
        for n in RECRUIT_NAMES:
            if n not in used:
                break
        else:
            n = f"{random.choice(RECRUIT_NAMES)[:11]}{len(used)}"
        self.k["names_used"].append(n)
        return n

    def _order_keys(self, st: Optional[State]) -> list[str]:
        """Living heroes' slots in the wanted order, or [] if the front three are right."""
        if st is None:
            return []
        alive = [h for h in st.party if h.alive]
        want = sorted(alive, key=lambda h: (FRONT_RANK.get(h.cls, 2), -h.max_hp))
        if {h.slot for h in want[:3]} == {h.slot for h in alive[:3]}:
            return []
        return [str(h.slot) for h in want]

    # ── combat ─────────────────────────────────────────────────────────────────
    def _combat(self, lines, low, label, st) -> Optional[Action]:
        if "(f)ight" in low and "(r)un" in low:
            foes = self._foes(low)
            first = self.combat is None
            if first:
                self.combat = {"foes": foes, "round": 0, "vopl": False, "pending": None,
                               "unknown_spells": set(), "hp_start": st.hp_fraction if st else 1.0,
                               "alive_start": sum(1 for h in st.party if h.alive) if st else 6}
                self.k["stats"]["fights"] += 1
            self.combat["round"] += 1
            self.combat["foes"] = foes or self.combat["foes"]
            reason = self._should_run(foes, st, first)
            if reason:
                self.combat["ran"] = True
                return Action(["R"], "Fleeing!", [f"The party flees from {foes or 'the foe'} ({reason})."])
            ev = [f"A fight begins: {foes}."] if first and foes else []
            return Action(["F"], f"Fighting {self._short(foes)}", ev)

        if "attack group" in low:
            return Action(["A"], f"Fighting {self._short(self._foes_now())}")
        if "spell to cast" in low and not (self.combat and self.combat.get("pending")):
            return None          # a spell prompt we didn't start: let the model sort it out
        if "spell to cast" in low:
            if "thou knowest not" in low:
                code, _ = self.combat["pending"]
                self.combat["unknown_spells"].add(code)
                self.combat["pending"] = None
                return Action(["SPACE"], "Spell failed")
            code, _ = self.combat["pending"]
            if re.search(r":\s*<", _joined(lines)) or low.rstrip().endswith("spell to cast:"):
                return Action([code, "RETURN"], f"Casting {code}")
            return Action([], f"Casting {code}")
        if "cast at" in low and self.combat and self.combat.get("pending"):
            code, target = self.combat["pending"]
            self.combat["pending"] = None
            return Action([target], f"Casting {code}")
        if "use these attack" in low:
            return Action(["Y"], f"Fighting {self._short(self._foes_now())}")
        if "has these options" in low or ("battle round" in low and "select an option" in low):
            return self._hero_turn(lines, st)
        return None

    def _should_run(self, foes: str, st: Optional[State], first: bool) -> str:
        """Why the party should flee this fight ('' = stand and fight)."""
        if st is None:
            return ""
        if st.hp_fraction < RUN_BELOW:
            return "badly wounded"
        if self._front_alive(st) < 2:
            return "the front line has fallen"
        if not first:
            return ""
        groups = [(int(n), name.strip()) for n, name in re.findall(r"(\d+) ([a-z' -]+?)(?:,| and |$)", foes)]
        count = sum(n for n, _ in groups)
        for _, name in groups:
            if self.k["danger"].get(self._species(name), {}).get("deadly"):
                return f"{name} are deadly"
        if count > 6 or (count > 4 and st.hp_fraction < 0.8):
            return f"{count} foes is too many"
        return ""

    @staticmethod
    def _species(name: str) -> str:
        name = name.strip().lower()
        return name[:-1] if name.endswith("s") else name

    def _hero_turn(self, lines, st: Optional[State]) -> Action:
        text = _joined(lines)
        name = text.split(" has these")[0].strip().upper()
        opts = _options(lines)
        hero = st.hero(name) if st else None
        cls = hero.cls if hero else ""
        sp = hero.sp if hero else 0
        c = self.combat or {}
        foes = self._short(c.get("foes", ""))
        if cls == "Conjurer" and "C" in opts and sp >= 3 and "ARFI" not in c.get("unknown_spells", ()):
            c["pending"] = ("ARFI", "A")
            return Action(["C"], f"{name.title()}: Arc Fire")
        if cls == "Magician" and "C" in opts and sp >= 3 and not c.get("vopl") \
                and "VOPL" not in c.get("unknown_spells", ()):
            c["vopl"] = True
            front = next((h.slot for h in st.party[:3] if h.alive), 1) if st else 1
            c["pending"] = ("VOPL", str(front))
            return Action(["C"], f"{name.title()}: Vorpal Plating")
        if "A" in opts:
            return Action(["A"], f"{name.title()} attacks {foes}".strip())
        if cls == "Rogue" and "H" in opts:
            return Action(["H"], f"{name.title()} hides")
        return Action(["D"], f"{name.title()} defends")

    def _end_combat(self, st: State) -> None:
        c = self.combat
        self.combat = None
        lost = max(0.0, c.get("hp_start", 1.0) - st.hp_fraction)
        died = c.get("alive_start", 6) - sum(1 for h in st.party if h.alive)
        for name in re.findall(r"\d+ ([a-z' -]+?)(?:,| and |$)", c.get("foes", "")):
            d = self.k["danger"].setdefault(self._species(name), {"fights": 0, "hp_lost": 0.0, "deaths": 0})
            d["fights"] += 1
            d["hp_lost"] += lost
            d["deaths"] += max(0, died)
            d["deadly"] = d["deaths"] > 0 or d["hp_lost"] / d["fights"] > 0.4
        self.k["stats"]["fled" if c.get("ran") else "won"] += 1
        self.pending_events.append(f"The fight with {c.get('foes') or 'the foe'} is over"
                                   + (" (the party fled)." if c.get("ran") else ": victory."))
        dead = [h for h in st.party if not h.alive]
        if dead and died > 0:
            self.k.setdefault("lost_classes", []).extend(h.cls for h in dead[-died:])
            self.pending_events.append(f"Fallen: {', '.join(h.name for h in dead[-died:])}.")

    def _foes(self, low: str) -> str:
        m = re.search(r"(?:you see|still face|in the form of) (.+?)\.", low)
        return m.group(1).replace(" ,", ",") if m else ""

    def _foes_now(self) -> str:
        return (self.combat or {}).get("foes", "")

    @staticmethod
    def _short(foes: str) -> str:
        m = re.search(r"\d+ ([a-z' -]+)", foes or "")
        return m.group(1).strip().title() if m else "foes"

    @staticmethod
    def _front_alive(st: State) -> int:
        return sum(1 for h in st.party[:3] if h.alive)

    # ── buildings ──────────────────────────────────────────────────────────────
    def _building(self, label, lines, low, st) -> Optional[Action]:
        # Inside a building the party stands on its map square: learn what that code is.
        code = self.city[st.y][st.x] if (self.city and st and 0 <= st.x < 30 and 0 <= st.y < 30) else 0
        if code and code not in HOUSES and str(code) not in self.k["buildings"] \
                and label and self.combat is None and "(f)ight" not in low:
            intro = re.split(r"(?<=[.!?])\s", _joined(lines))[0][:80]
            self.k["buildings"][str(code)] = f"{label}: {intro}"
            self.pending_events.append(f"The party discovers {label} ({intro})")
        opts = _options(lines)
        where = label.lower()

        if "who needeth healing" in low or ("will cost" in low and "who will pay" in low):
            return self._temple(low, st)
        if "review" in where and (self.target_kind == "review" or self.errand == "review"):
            self._arrived("review")
            self.errand = "review"
            m = re.search(r"needs? (\d+) more", low)
            if m and st:                                  # "<HERO> needs 1970 more experience"
                who = next((h for h in st.party if h.name.lower() in low), None)
                if who:
                    self.k.setdefault("next_level_xp", {})[who.name] = who.xp + int(m.group(1))
            return _rescue("Have each of the six heroes reviewed for (A)dvancement one after another, "
                           "and learn new spells with (S)pell Acquiring for the magic users if offered "
                           "and affordable; never use Class Change. Then leave.",
                           "Before the Review Board")
        if "garth" in low or "p)urc" in low or "purchase" in low or \
                ("would you like to" in low and "(b)uy" in low):
            return self._shop(lines, low, st)
        if "E" in opts and re.search(r"\(e\)xit", low):
            self.just_left = True
            return Action(["E"], f"Leaving {label or 'the building'}")
        if "L" in opts and re.search(r"\(l\)eave", low):
            self.just_left = True
            return Action(["L"], f"Leaving {label or 'the building'}")
        return self._waiting(low)

    def _shop(self, lines, low: str, st: Optional[State]) -> Action:
        """Garth's: each shopper buys their kit, cheapest essentials first, with own gold."""
        if self.errand != "shop":                        # first look inside: the shopping list
            self.errand = "shop"
            self._arrived("shop")
            self.shopping = {h.name: [i for i in KIT[h.cls]] for h in self._shoppers(st)} if st else {}
            for name in self.shopping:
                self.k["shop_tries"][name] = self.k["shop_tries"].get(name, 0) + 1
        if "which of you" in low:                        # the counter
            left = [n for n, items in self.shopping.items() if items]
            hero = st.hero(left[0]) if (st and left) else None
            if hero is None:
                self.just_left = True
                return Action(["E"], "Leaving Garth's")
            self.shop_hero = hero.name
            return Action([str(hero.slot)], f"{hero.name.title()} at Garth's")
        m = re.search(r"(?:you have|gold :)\s*(\d+)", low)
        gold = int(m.group(1)) if m else 0
        items = self.shopping.get(getattr(self, "shop_hero", ""), [])
        if getattr(self, "shop_gold", None) is not None and "p)urc" in low:
            tried = items.pop(0) if items else ""       # after a purchase: bought, or refused
            if tried and gold < self.shop_gold:
                self.to_equip.add(self.shop_hero)
                self.pending_events.append(f"{self.shop_hero} buys a {tried.lower()}.")
            self.shop_gold = None
        while items and CATALOG_PRICE[items[0]] > gold:
            items.pop(0)                                 # can't afford: skip it
        if "would you like to" in low:                   # a hero's menu
            if items:
                return Action(["B"], f"Buying {items[0].lower()}")
            self.shopping[getattr(self, "shop_hero", "")] = []
            return Action(["E"], "Done shopping")
        if "purchase" in low and "(1-9)" in low:
            return Action([str(self.shop_pick)] if getattr(self, "shop_pick", 0) else ["\x1b"],
                          f"Buying {items[0].lower() if items else 'gear'}")
        if "p)urc" in low:                               # the item list: find the next item
            if not items:
                return Action(["B"], "Done buying")
            want = items[0][:9].lower()
            for i, l in enumerate(lines):
                mm = re.match(r"\s*(\d)\.(.{1,9})", l)
                if mm and mm.group(2).strip().lower() == want.strip():
                    self.shop_pick, self.shop_gold = int(mm.group(1)), gold
                    return Action(["P"], f"Buying {items[0].lower()}")
            return Action(["F"], "Browsing the wares")
        return self._waiting(low)

    def _equip(self, lines, low) -> Action:
        """On a hero's sheet: equip anything bought but not yet equipped."""
        for l in lines:
            mm = re.match(r"\s*(\d)\)\s+(\S.*)", l)     # "1) Short Sword" (equipped: "1)·Short Sword")
            if mm and (self.equip_hero, mm.group(2)) not in self.equip_tried:
                self.equip_tried.add((self.equip_hero, mm.group(2)))
                self.equip_pick = mm.group(1)
                return Action(["E"], f"Equipping {mm.group(2).lower()}")
        self.to_equip.discard(self.equip_hero)
        return Action(["SPACE"], "Ready")

    def _temple(self, low: str, st: Optional[State]) -> Action:
        """Heal the most wounded first, paid by the richest purse; skip what nobody can afford."""
        self._arrived("heal")
        if st is None:
            return Action([], "At the temple")
        if "who will pay" in low:
            m = re.search(r"cost (\d+)", low)
            cost = int(m.group(1)) if m else 10 ** 9
            payers = sorted((h for h in st.party if h.alive), key=lambda h: -h.gold)
            patient = self.temple_patient
            if payers and payers[0].gold >= cost:
                if patient:
                    self.temple_skip.add(patient.name)       # done with them (healed or raised)
                    self.pending_events.append(
                        f"The temple {'raises' if not patient.alive else 'heals'} {patient.name} "
                        f"for {cost} gold.")
                return Action([str(payers[0].slot)], f"Paying {cost} gold")
            if patient:
                self.temple_skip.add(patient.name)
            return Action(["\x1b"], "Too costly")
        # "Who needeth healing?"
        rich = max((h.gold for h in st.party if h.alive), default=0)
        patients = [h for h in st.party if h.name not in self.temple_skip
                    and self._treatable(h) and _heal_cost(h) <= rich]
        if not patients:
            self.temple_skip.clear()
            self.temple_patient = None
            self.just_left = True
            self.heal_after = time.monotonic() + HEAL_COOLDOWN
            return Action(["E"], "Leaving the temple")
        patients.sort(key=lambda h: (h.alive, h.hp - h.max_hp))    # the dead, then the worst hurt
        self.temple_patient = patients[0]
        return Action([str(patients[0].slot)], f"Healing {patients[0].name.title()}")

    # ── streets ────────────────────────────────────────────────────────────────
    def _street(self, st: State) -> Action:
        events, self.pending_events = self.pending_events, []
        if self.city is None:
            return Action([], "Reading the map")      # the agent loads the map, then asks again
        if self.city[st.y][st.x] and not self.just_left:
            # On a building's square: its screen is coming. (After leaving, the party
            # stays on that square until it steps off.)
            self.entering_waits += 1
            if self.entering_waits <= 3:
                return Action([], "Entering", events)
        self.entering_waits = 0
        if not self.city[st.y][st.x]:
            self.just_left = False
            self.errand = ""                          # back on the street: any errand is over

        self.stuck = self.stuck + 1 if st.pos == self.last_pos else 0
        self.last_pos = st.pos
        if self.stuck > 6:                            # something blocks the plan: pick anew
            self.target, self.target_kind, self.stuck = None, "", 0

        for name in list(self.to_equip):          # purchases to put on: open that hero's sheet
            h = st.hero(name)
            if h is None or not h.alive:
                self.to_equip.discard(name)
                continue
            self.equip_hero = name
            return Action([str(h.slot)], f"Equipping {name.title()}", events)
        self.equip_hero = ""

        kind, cell = self._urgent_goal(st)
        if kind and (kind != self.target_kind or self.target is None):
            self.target, self.target_kind = cell, kind
        elif not kind and self.target_kind in ("recruit", "heal", "shop", "review"):
            self.target, self.target_kind = None, ""  # that errand no longer applies
        if self.target is None:
            if random.random() < SURVEY_CHANCE:
                self.target, self.target_kind = self._nearest_unknown_special(st.pos), "survey"
            if self.target is None:
                self._choose_patrol_target(st)

        target = self.target
        path = navigate.bfs(st.pos, lambda p: p == target, self._open)
        if path is None:
            self.target, self.target_kind = None, ""
            return Action(["L"], "Looking around", events)
        if not path:                                  # standing on the target square
            self._arrived(self.target_kind)
            return Action([], "Arrived", events)
        keys = navigate.first_step_keys(st.pos, st.facing, path)
        nx, ny = path[0]
        if self.city[ny][nx]:
            # Houses are entered by kicking the door in; if walking into any other
            # building doesn't get the party inside, kick that door too.
            self.bumps += 1
            if self.city[ny][nx] in HOUSES or self.bumps > 1:
                keys = keys[:-1] + "K"
        else:
            self.bumps = 0
        doing = {"heal": "Seeking a temple", "kick": "Kicking in a door", "survey": "Exploring the city",
                 "review": "To the Review Board", "recruit": "To the Guild",
                 "shop": "To Garth's shop"}.get(self.target_kind, "Patrolling")
        return Action(list(keys), doing, events)

    def _arrived(self, kind: str) -> None:
        """An errand's building has been reached: stop steering toward it."""
        if self.target_kind == kind:
            self.target, self.target_kind = None, ""
            if kind == "review":
                self.k["reviewed_at"] = self.k["stats"]["won"]

    def _urgent_goal(self, st: State) -> tuple[str, Optional[tuple[int, int]]]:
        alive = [h for h in st.party if h.alive]
        dead = [h for h in st.party if not h.alive]
        if dead and not self._can_raise(st) and self.recruits_this_session < 8:
            return "recruit", GUILD
        rich = max((h.gold for h in alive), default=0)
        hurt = [h for h in st.party if self._treatable(h) and _heal_cost(h) <= rich]
        needs = st.hp_fraction < HEAL_BELOW or any(h.hp < HERO_HEAL_BELOW * h.max_hp for h in alive) \
            or any(not h.alive for h in hurt)
        if needs and hurt and time.monotonic() >= self.heal_after:
            temple = self._nearest_building("temple", st.pos)
            if temple:
                return "heal", temple
            unknown = self._nearest_unknown_special(st.pos)
            if unknown:
                return "survey", unknown
        if self._shoppers(st):
            shop = self._nearest_building("garth", st.pos)
            if shop:
                return "shop", shop
        if self._review_due(st):
            board = self._nearest_building("review", st.pos)
            if board:
                return "review", board
        return "", None

    @staticmethod
    def _treatable(h) -> bool:
        """Wounded, or dead but worth raising."""
        return (h.alive and h.hp < h.max_hp) or (not h.alive and h.level >= KEEP_LEVEL)

    def _review_due(self, st: State) -> bool:
        """A hero has reached the experience the Review Board asked for; with no such
        figure yet for anyone, every REVIEW_EVERY victories."""
        need = self.k.get("next_level_xp", {})
        if any(h.alive and h.name in need and h.xp >= need[h.name] for h in st.party):
            return True
        if any(h.name in need for h in st.party):
            return False
        return self.k["stats"]["won"] - self.k.get("reviewed_at", 0) >= REVIEW_EVERY

    def _can_raise(self, st: State) -> bool:
        return not self._to_retire(st)

    def _to_retire(self, st: Optional[State]) -> list:
        """Dead heroes to drop from the party: below KEEP_LEVEL (not worth raising) or
        too costly to raise with the gold the living carry."""
        if st is None:
            return []
        rich = max((h.gold for h in st.party if h.alive), default=0)
        return [h for h in st.party if not h.alive and (h.level < KEEP_LEVEL or _heal_cost(h) > rich)]

    def _shoppers(self, st: Optional[State]) -> list:
        if st is None:
            return []
        tries = self.k["shop_tries"]
        return [h for h in st.party if h.alive and h.cls in KIT and h.ac >= 8
                and h.gold >= 30 and tries.get(h.name, 0) < 2]

    def _open(self, p) -> bool:
        x, y = p
        return 0 <= x < 30 and 0 <= y < 30 and self.city[y][x] == 0

    def _choose_patrol_target(self, st: State) -> None:
        streets, doors = [], []
        for y in range(30):
            for x in range(30):
                if abs(x - GUILD[0]) + abs(y - GUILD[1]) > PATROL_RADIUS:
                    continue
                v = self.city[y][x]
                if v == 0:
                    streets.append((x, y))
                elif v in HOUSES and any(self._open(n) for _, n in navigate.neighbours((x, y))):
                    doors.append((x, y))
        if doors and random.random() < KICK_CHANCE:
            self.target, self.target_kind = random.choice(doors), "kick"
        else:
            self.target, self.target_kind = random.choice(streets), "patrol"

    def _nearest_unknown_special(self, pos) -> Optional[tuple[int, int]]:
        """Closest reachable building of a kind the party hasn't been inside yet."""
        known = set(self.k["buildings"])
        cells = [(x, y) for y in range(30) for x in range(30)
                 if self.city[y][x] not in HOUSES and self.city[y][x] and str(self.city[y][x]) not in known
                 and any(self._open(n) for _, n in navigate.neighbours((x, y)))]
        return self._closest(pos, cells)

    def _nearest_building(self, kind: str, pos) -> Optional[tuple[int, int]]:
        codes = {int(c) for c, n in self.k["buildings"].items() if kind in n.lower()
                 and "mad god" not in n.lower()}          # the Mad God's temple doesn't heal
        cells = [(x, y) for y in range(30) for x in range(30) if self.city[y][x] in codes]
        return self._closest(pos, cells)

    def _closest(self, pos, cells) -> Optional[tuple[int, int]]:
        best = None
        for c in cells:
            path = navigate.bfs(pos, lambda p, c=c: p == c, self._open)
            if path is not None and (best is None or len(path) < best[0]):
                best = (len(path), c)
        return best[1] if best else None

    # ── anything else ──────────────────────────────────────────────────────────
    def _waiting(self, low: str) -> Optional[Action]:
        """No recognised prompt: messages are playing out. Wait a little, then nudge
        with SPACE; if that goes nowhere, give up (the agent asks the model)."""
        quiet = time.monotonic() - self.quiet_since
        if quiet < 2.5:
            return Action([], "Watching")
        if quiet < 12:
            return Action(["SPACE"], "Continuing")
        return None
