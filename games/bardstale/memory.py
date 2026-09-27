"""
Game state read straight from the emulated Apple II's memory (Apple II Bard's Tale).

Addresses were found by diffing RAM snapshots and tapping the renderer's reads:

    $0000  party Y (north is +1)          $0001  party X (east is +1)
    $0002  facing: 0 N, 1 E, 2 S, 3 W
    $DA80  six 128-byte character records (language-card RAM), in party order:
             +$00 name (16 bytes, high-bit ASCII, $FF padded)
             +$14 experience, 12 decimal digits one per byte   +$20 level  +$22 max level
             +$24 gold (12 digits, same format; unconfirmed until the party has gold)
             +$30 max HP  +$32 current HP  +$34 max SP  +$36 current SP  (16-bit big-endian)
             +$38 class   +$39 race   +$3F armor (AC = 10 - value)
             +$50 inventory (flag, item) pairs
    $A92E  the map-cell lookup: row base = $F800 + ($A972+row)<<8 | ($A954+row); 30x30
           bytes, 0 = open street; rows stored bottom-up from $FB66 (row 0) to $F800.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

from games.bardstale import emulator

PARTY_BASE = 0xDA80
RECORD = 0x80
CLASSES = {0: "Warrior", 1: "Wizard", 2: "Sorcerer", 3: "Conjurer", 4: "Magician",
           5: "Rogue", 6: "Bard", 7: "Paladin", 8: "Hunter", 9: "Monk"}
DIRS = {0: (0, 1), 1: (1, 0), 2: (0, -1), 3: (-1, 0)}   # facing -> (dx, dy)
FACING_NAMES = {0: "north", 1: "east", 2: "south", 3: "west"}


@dataclass
class Hero:
    slot: int
    name: str
    cls: str
    max_hp: int
    hp: int
    max_sp: int
    sp: int
    level: int = 1
    xp: int = 0
    gold: int = 0
    ac: int = 10

    @property
    def alive(self) -> bool:
        return self.hp > 0


@dataclass
class State:
    x: int
    y: int
    facing: int
    party: list[Hero] = field(default_factory=list)

    @property
    def pos(self) -> tuple[int, int]:
        return self.x, self.y

    def hero(self, name_or_class: str) -> Optional[Hero]:
        key = name_or_class.upper()
        return next((h for h in self.party if h.name == key or h.cls.upper() == key), None)

    @property
    def hp_fraction(self) -> float:
        total = sum(h.max_hp for h in self.party)
        return sum(max(0, h.hp) for h in self.party) / total if total else 0.0


def _be16(b: bytes, i: int) -> int:
    return (b[i] << 8) | b[i + 1]


def _digits(b: bytes) -> int:
    return int("".join(str(d) for d in b)) if all(d <= 9 for d in b) else -1


def _hero(slot: int, rec: bytes) -> Optional[Hero]:
    raw = rec[:16]
    if raw[0] in (0x00, 0xFF):
        return None
    name = bytes(c & 0x7F for c in raw if c != 0xFF).decode("ascii", "replace").strip()
    if not name or not all(32 <= ord(ch) < 127 for ch in name):
        return None
    return Hero(slot=slot, name=name, cls=CLASSES.get(rec[0x38], f"class{rec[0x38]}"),
                max_hp=_be16(rec, 0x30), hp=_be16(rec, 0x32),
                max_sp=_be16(rec, 0x34), sp=_be16(rec, 0x36), level=_be16(rec, 0x20),
                xp=_digits(rec[0x14:0x20]), gold=_digits(rec[0x24:0x30]), ac=10 - rec[0x3F])


def read_state() -> Optional[State]:
    """Position, facing and party, in one emulator round trip. None if unavailable."""
    got = emulator.peek((0x0000, 3), (PARTY_BASE, RECORD * 6))
    if not got:
        return None
    zp, recs = got
    party = []
    for i in range(6):
        h = _hero(i + 1, recs[i * RECORD:(i + 1) * RECORD])
        if h:
            party.append(h)
    return State(x=zp[1], y=zp[0], facing=zp[2] & 3, party=party)


def read_map() -> Optional[list[list[int]]]:
    """The current 30x30 map as grid[y][x] (city: 0 = street)."""
    got = emulator.peek((0xA954, 30), (0xA972, 30), (0xF800, 0x400))
    if not got:
        return None
    lo, hi, block = got
    grid = []
    for y in range(30):
        base = ((0xF8 + hi[y]) << 8 | lo[y]) - 0xF800
        if not 0 <= base <= 0x400 - 30:
            return None
        grid.append(list(block[base:base + 30]))
    return grid
