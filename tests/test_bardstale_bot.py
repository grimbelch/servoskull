"""The Bard's Tale autopilot's decisions (run: python -m pytest tests).

Screens are given as the text games/bardstale/screen_text reads off the game; the
city is a synthetic grid (0 = street), so no game data is needed.
"""

from games.bardstale import bot as B, navigate
from games.bardstale.memory import Hero, State


def city():
    grid = [[1] * 30 for _ in range(30)]          # houses everywhere...
    for x in range(30):
        grid[15][x] = 0                            # ...an east-west street at y=15
    for y in range(30):
        grid[y][25] = 0                            # ...and a north-south one at x=25
    grid[15][24] = 11                              # the Guild, west of (25,15)
    grid[20][26] = 33                              # a temple, east of (25,20)
    grid[18][26] = 28                              # Garth's, east of (25,18)
    return grid


def make_bot(**knowledge):
    b = B.Bot(dict(knowledge))
    b.city = city()
    return b


def hero(slot, name, cls, hp, max_hp, gold=0, level=1, sp=0, ac=5):
    return Hero(slot, name, cls, max_hp, hp, sp, sp, level, 0, gold, ac)


def screen(label, *lines, party=("x",)):
    return {"location": label, "message": list(lines), "party": list(party)}


PARTY = [hero(1, "BRIAN THE FIST", "Paladin", 28, 30), hero(2, "SAMSON", "Warrior", 28, 28),
         hero(3, "EL CID", "Bard", 20, 20), hero(4, "MARKUS", "Rogue", 24, 24),
         hero(5, "MERLIN", "Conjurer", 16, 16, sp=20), hero(6, "OMAR", "Magician", 20, 20, sp=14)]


def at(x, y, party=PARTY, facing=1):
    return State(x, y, facing, list(party))


# ── navigation ─────────────────────────────────────────────────────────────────

def test_route_planning_turns_then_steps():
    grid = city()
    path = navigate.bfs((25, 15), lambda p: p == (25, 18), lambda p: grid[p[1]][p[0]] == 0)
    assert path == [(25, 16), (25, 17), (25, 18)]
    assert navigate.first_step_keys((25, 15), 1, path) == "JI"     # facing east: turn left (north)
    assert navigate.turn_keys(0, 2) == "LL"


# ── combat ─────────────────────────────────────────────────────────────────────

FIGHT = ("Before you, you", "see 3 Kobolds.", "", "Will your", "stalwart band", "choose to (F)ight", "or (R)un?")


def test_fights_small_groups_and_flees_big_or_deadly_ones():
    assert make_bot().act(screen("Kobolds", *FIGHT), at(25, 15)).keys == ["F"]
    many = ("Before you, you", "see 8 Barbarians,", "and 1 Mercenary.", "Will your", "choose to (F)ight", "or (R)un?")
    assert make_bot().act(screen("Barbarians", *many), at(25, 15)).keys == ["R"]
    wary = make_bot(danger={"kobold": {"fights": 1, "hp_lost": 0.5, "deaths": 3, "deadly": True, "level": 1}})
    assert wary.act(screen("Kobolds", *FIGHT), at(25, 15)).keys == ["R"]
    grown = [hero(h.slot, h.name, h.cls, h.hp, h.max_hp, level=3) for h in PARTY]
    assert make_bot(danger=wary.k["danger"]).act(screen("Kobolds", *FIGHT), at(25, 15, grown)).keys == ["F"]


def test_monster_names_are_singular():
    assert [B.Bot._species(n) for n in ("thieves", "mercenaries", "orcs", "mad dogs", "kobold")] == \
        ["thief", "mercenary", "orc", "mad dog", "kobold"]


def test_combat_round_commands():
    b = make_bot()
    b.act(screen("Kobolds", *FIGHT), at(25, 15))
    menu = lambda who, *opts: screen("Kobolds", f"{who} has these", "options this", "battle round:", "", *opts,
                                     "", "Select an option.")
    assert b.act(menu("BRIAN THE FIST", "(A)ttack foes", "(P)arty attack", "(D)efend"), at(25, 15)).keys == ["A"]
    assert b.act(screen("Kobolds", "(a) 3 Kobolds", "Attack group (A-B)", "(esc) to abort"), at(25, 15)).keys == ["A"]
    assert b.act(menu("MARKUS", "(P)arty attack", "(D)efend", "(H)ide in shadows"), at(25, 15)).keys == ["H"]
    # Merlin casts Arc Fire at the first foe group: C, the code, then the group letter.
    assert b.act(menu("MERLIN", "(P)arty attack", "(D)efend", "(C)ast a spell"), at(25, 15)).keys == ["C"]
    assert b.act(screen("Kobolds", "battle round:", "Select an option.", "Spell to cast:", ":               <"),
                 at(25, 15)).keys == ["ARFI", "RETURN"]
    assert b.act(screen("Kobolds", "(a) 3 Kobolds", "Cast at member", "/(1-6) or group", "(A-B)"),
                 at(25, 15)).keys == ["A"]
    # Omar enchants the first living front-liner's weapon.
    assert b.act(menu("OMAR", "(P)arty attack", "(D)efend", "(C)ast a spell"), at(25, 15)).keys == ["C"]
    b.act(screen("Kobolds", "Spell to cast:", ":               <"), at(25, 15))
    assert b.act(screen("Kobolds", "Cast at member", "/(1-6)"), at(25, 15)).keys == ["1"]
    assert b.act(screen("Kobolds", "Use these attack", "commands? (Y-N)"), at(25, 15)).keys == ["Y"]
    # Never a party attack, even when nothing else is offered.
    assert b.act(menu("SAMSON", "(P)arty attack", "(D)efend"), at(25, 15)).keys == ["D"]


# ── streets ────────────────────────────────────────────────────────────────────

def test_street_ignores_plain_messages_but_not_questions():
    b = make_bot()
    walk = b.act(screen("Skara Brae", "You are on Main", "Street."), at(25, 15))
    assert walk.keys and walk.keys[-1] in ("I", "K", "L")
    asked = make_bot().act(screen("Skara Brae", "Who goes there?"), at(25, 15))
    assert asked is None or asked.keys in ([], ["SPACE"])


def test_new_order_one_hero_per_key():
    b = make_bot()
    b.order_plan = [(3, "EL CID"), (1, "BRIAN THE FIST"), (2, "SAMSON")]
    assert b.act(screen("Skara Brae", "New Order:", "", "1>"), at(25, 15)).keys == ["3"]
    assert b.act(screen("Skara Brae", "New Order:", "1> EL CID", "2>"), at(25, 15)).keys == ["1"]


# ── the Guild: replace the fallen ──────────────────────────────────────────────

GUILD_MENU = ("Thou art in the", "Guild of", "Adventurers.", "", "(C)heck Roster", "(A)dd member",
              "(R)emove member", "(D)isk Options", "(N)ew order", "(1-6) View member", "(E)xit Guild")


def test_low_level_dead_are_retired_deleted_and_replaced():
    b = make_bot()
    party = [hero(1, "OMAR", "Magician", 20, 20, gold=189), hero(2, "SAMSON", "Warrior", 0, 28, level=2)]
    b.k["lost_classes"] = ["Warrior"]
    assert b._urgent_goal(at(25, 15, party))[0] == "recruit"
    g = lambda *lines: b.act(screen("The Guild", *lines), at(24, 15, party))
    assert g(*GUILD_MENU).keys == ["R"]
    b.guild_last = ("", 0.0)
    assert g("Drop character", "number (1-6) from", "the party ?").keys == ["2"]
    party = party[:1]                               # Samson is gone from the party
    g = lambda *lines: b.act(screen("The Guild", *lines), at(24, 15, party))
    b.guild_last = ("", 0.0)
    assert g(*GUILD_MENU).keys == ["D"]
    b.guild_last = ("", 0.0)
    disk = ("Disk Options:", "", "(C)reate member", "(S)ave party", "(D)elete member", "(L)eave the game",
            "(E)xit disk op")
    assert g(*disk).keys == ["D"]                   # delete the level-2 corpse first
    assert g("Delete Character", "", "Enter a name--", ":               <").keys == ["SAMSON", "RETURN"]
    b.guild_last = ("", 0.0)
    assert g(*disk).keys == ["C"]                   # then create a replacement Warrior
    name = b.recruit["name"]
    assert g("Select a race for", "your new", "character:", "(1) Human", "(3) Dwarf").keys == ["3"]
    assert g("Character X", "St:18 IQ: 6 Dx: 8", "(5) Rogue", "(ESC) to abort").keys == ["\x1b"]  # reroll
    assert g("Character X", "St:17 IQ: 7 Dx: 9", "(0) Warrior", "(5) Rogue").keys == ["0"]
    assert g("Enter a name--", ":               <").keys == [name, "RETURN"]
    b.guild_last = ("", 0.0)
    assert g(*disk).keys == ["E"]
    b.guild_last = ("", 0.0)
    assert g(*GUILD_MENU).keys == ["A"]
    assert g("Load Character", "", "Enter a name--", ":               <").keys == [name, "RETURN"]


def test_guild_waits_for_the_disk_before_repeating_itself():
    b = make_bot()
    party = [hero(1, "OMAR", "Magician", 20, 20), hero(2, "SAMSON", "Warrior", 0, 28)]
    first = b.act(screen("The Guild", *GUILD_MENU), at(24, 15, party))
    again = b.act(screen("The Guild", *GUILD_MENU), at(24, 15, party))
    assert first.keys == ["R"] and again.keys == []


# ── the temple ─────────────────────────────────────────────────────────────────

WELCOME = ("Welcome, oh weary", "ones, to our", "humble temple.", "Who needeth", "healing?", "",
           "Enter /(1-6) or", "(E)xit temple")


def test_temple_heals_the_worst_first_and_skips_what_nobody_can_afford():
    b = make_bot()
    party = [hero(1, "EL CID", "Bard", 9, 20, gold=189, level=2), hero(2, "MARKUS", "Rogue", 20, 24, gold=50, level=2),
             hero(3, "BRIAN THE FIST", "Paladin", 0, 30, level=3)]
    t = lambda *lines: b.act(screen("Temple", *lines), at(26, 20, party))
    assert t(*WELCOME).keys == ["1"]                                    # El Cid: worst hurt (Brian unaffordable)
    assert t("EL CID has wounds", "which need", "tending. It will", "cost 110 in gold.", "Who will pay?",
             "/(1-6)").keys == ["1"]                                    # the richest purse pays
    assert t(*WELCOME).keys == ["2"]
    assert t("MARKUS has wounds", "It will", "cost 400 in gold.", "Who will pay?", "/(1-6)").keys == ["\x1b"]
    assert t(*WELCOME).keys == ["E"]


# ── Garth's shop ───────────────────────────────────────────────────────────────

def test_shopping_buys_the_kit_then_equips_it():
    b = make_bot()
    b.target_kind = "shop"
    party = lambda gold: [hero(1, "BRIAN THE FIST", "Paladin", 28, 30), hero(2, "VEX", "Warrior", 18, 18, gold=gold, ac=10)]
    s = lambda label, gold, *lines: b.act(screen(label, *lines), at(26, 18, party(gold)))
    counter = ("Welcome to", "Garth's Equipment", "Shoppe", "Which of you is", "interested in my", "fine wares?",
               "/(1-6) or", " (E)xit the shoppe")
    menu = lambda g: ("Greetings, VEX", "Would you like to:", "(B)uy an item", "(S)ell an item", "(E)xit",
                      f"You have {g} gold.")
    page = lambda g, tail="P)urc F)orw B)ack": ("1.Torch     5", "2.Lamp      15", "3.Broadswor 80",
                                                 "4.Short Swo 30", "5.Dagger    20", "", f"Gold :   {g}", tail)
    assert s("The Shoppe", 113, *counter).keys == ["2"]
    assert s("The Shoppe", 113, *menu(113)).keys == ["B"]
    assert s("The Shoppe", 113, *page(113)).keys == ["P"]
    assert s("The Shoppe", 113, *page(113, "Purchase /(1-9)")).keys == ["4"]
    assert s("The Shoppe", 83, *page(83)).keys == ["F"]                # sword bought; armour is further on
    b.shopping["VEX"] = []
    assert s("The Shoppe", 83, *page(83)).keys == ["\x1b"]             # done: leave the list (B only scrolls)
    assert "VEX" in b.to_equip
    # Back on the street: open Vex's sheet and equip what's unequipped.
    b.errand, b.just_left = "", True
    street = b.act(screen("Skara Brae"), at(25, 18, party(13)))
    assert street.keys == ["2"]
    sheet = ["VEX", "1) Short Sword", "2)", "Choose: (E,T,D,P)"]
    assert b.act(screen("Skara Brae", *sheet), at(25, 18, party(13))).keys == ["E"]
    assert b.act(screen("Skara Brae", "VEX", "1) Short Sword", "Equip /(1-8) or 0"), at(25, 18, party(13))).keys == ["1"]
    sheet[1] = "1)·Short Sword"
    assert b.act(screen("Skara Brae", *sheet), at(25, 18, party(13))).keys == ["SPACE"]
    assert not b.to_equip
