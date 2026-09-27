"""
Route planning on the Bard's Tale grid.

Coordinates: x east, y north, facing 0 N / 1 E / 2 S / 3 W (games/bardstale/memory.py).
Keys (Apple II): I = step forward, L = turn right, J = turn left.
"""

from __future__ import annotations

from collections import deque
from typing import Callable, Iterable, Optional

from games.bardstale.memory import DIRS

Pos = tuple[int, int]


def neighbours(p: Pos) -> Iterable[tuple[int, Pos]]:
    for f, (dx, dy) in DIRS.items():
        yield f, (p[0] + dx, p[1] + dy)


def bfs(start: Pos, is_goal: Callable[[Pos], bool], passable: Callable[[Pos], bool],
        limit: int = 2000) -> Optional[list[Pos]]:
    """Shortest path of cells from start (exclusive) to the first goal cell (inclusive)."""
    if is_goal(start):
        return []
    prev: dict[Pos, Optional[Pos]] = {start: None}
    q = deque([start])
    while q and len(prev) < limit:
        cur = q.popleft()
        for _, nxt in neighbours(cur):
            if nxt in prev:
                continue
            if is_goal(nxt):
                path = [nxt]
                while cur != start:
                    path.append(cur)
                    cur = prev[cur]
                return path[::-1]
            if passable(nxt):
                prev[nxt] = cur
                q.append(nxt)
    return None


def turn_keys(facing: int, want: int) -> str:
    d = (want - facing) % 4
    return {0: "", 1: "L", 2: "LL", 3: "J"}[d]


def direction(a: Pos, b: Pos) -> int:
    for f, (dx, dy) in DIRS.items():
        if (a[0] + dx, a[1] + dy) == b:
            return f
    raise ValueError(f"{a} and {b} are not adjacent")


def first_step_keys(pos: Pos, facing: int, path: list[Pos]) -> str:
    """Keys that take the first step of `path`: turn toward it, then I."""
    return turn_keys(facing, direction(pos, path[0])) + "I"
