"""Necromunda dice as actual cubes, tumbling in three dimensions.

A dice is drawn as a cube carrying the six faces it really has -- an Injury
dice shows two crosses, three bursts and a skull, because that is what is
moulded on it -- and it turns in space, showing whichever sides happen to face
the viewer. It lands with the rolled face square to the front.

The faces come from ``core.dice_faces`` as geometry rather than drawing calls,
which is what makes this possible: a polygon's points can be carried onto the
side of a turning cube, while an ``ImageDraw.ellipse`` cannot.

Axes are the screen's: x right, y DOWN, z into the screen. The viewer sits at
-z, so a face is toward us when its normal has a negative z, and the front face
is the one whose outward normal is (0, 0, -1). Each face's u and v are chosen so
that ``u x v == -n``, which keeps every symbol the right way round rather than
mirrored on half the cube.
"""
from __future__ import annotations

import math

from core import dice_faces

# (normal, u, v) per face, front first so the rolled face can be put there.
FACES: tuple[tuple[tuple[float, float, float], ...], ...] = (
    ((0, 0, -1), (1, 0, 0), (0, 1, 0)),    # front, toward the viewer
    ((1, 0, 0), (0, 0, 1), (0, 1, 0)),     # right
    ((0, -1, 0), (1, 0, 0), (0, 0, -1)),   # top
    ((-1, 0, 0), (0, 0, -1), (0, 1, 0)),   # left
    ((0, 1, 0), (1, 0, 0), (0, 0, 1)),     # bottom
    ((0, 0, 1), (-1, 0, 0), (0, 1, 0)),    # back
)

# How the six sides of each kind of dice are laid out, in the real proportions:
# an Injury dice carries two Injured, three Serious Injury and one Out of
# Action. Opposites are not modelled -- nobody reads the far side of a dice.
_SIDES: dict[str, tuple[str, ...]] = {
    "injury": ("cross", "cross", "starburst", "starburst", "starburst", "skull"),
    "firepower": ("ammo", "holes1", "holes1", "holes2", "holes2", "holes3"),
    "scatter": ("crosshair", "crosshair", "arrow", "arrow", "arrow", "arrow"),
    "d6": ("pip",) * 6,
}

_CAMERA_DISTANCE = 3.4
_FOCAL = 2.6


def sides_for(kind: str, landed: str) -> list[str]:
    """The six sides of a dice of this kind, with ``landed`` at the front.

    The rolled face has to be the one left facing the viewer, and the other
    five are whatever else that dice carries.
    """
    pool = list(_SIDES.get(kind, ("pip",) * 6))
    if landed in pool:
        pool.remove(landed)
    else:
        pool = pool[:5]
    return [landed] + pool[:5]


def pip_values(front: int) -> list[int]:
    """The six pip counts in FACES order, with ``front`` facing the viewer.

    Opposite faces of a real dice sum to seven, so the back is set from the
    front and the other four are paired off the same way. Without this every
    cube showed a one on its front face whatever had been rolled, and the dice
    flashed the wrong number as it came to rest.
    """
    front = max(1, min(6, int(front)))
    back = 7 - front
    rest = [v for v in (1, 2, 3, 4, 5, 6) if v not in (front, back)]
    right, top = rest[0], rest[1]
    # FACES order: front, right, top, left, bottom, back.
    return [front, right, top, 7 - right, 7 - top, back]


def _rotate(point, rx: float, ry: float, rz: float):
    x, y, z = point
    cx, sx = math.cos(rx), math.sin(rx)
    y, z = y * cx - z * sx, y * sx + z * cx
    cy, sy = math.cos(ry), math.sin(ry)
    x, z = x * cy + z * sy, -x * sy + z * cy
    cz, sz = math.cos(rz), math.sin(rz)
    x, y = x * cz - y * sz, x * sz + y * cz
    return x, y, z


def _project(point, cx: float, cy: float, scale: float):
    x, y, z = point
    k = scale * _FOCAL / (z + _CAMERA_DISTANCE)
    return cx + x * k, cy + y * k


# A cube that fills the aperture face-on overflows it when tilted: a corner
# projects to 0.889 * scale, while a face-on side reaches only 0.448 * scale.
# TUMBLING is the largest that never clips while turning; LANDED matches the
# flat dice of the same nominal size, so handing over to the flat renderer once
# the cube is square-on is not a visible jump.
SCALE_TUMBLING = 0.90
SCALE_LANDED = 1.25


def draw_die(draw, cx: float, cy: float, size: float, colour, void,
             sides: list[str], detail=None,
             angles: tuple[float, float, float] = (0.0, 0.0, 0.0),
             scale_factor: float = SCALE_TUMBLING) -> None:
    """Draw one cube, turned by ``angles`` (degrees about x, y, z).

    Only the sides facing the viewer are drawn. On a convex cube at most three
    can face us at once and they never overlap, so they need no depth sorting.
    Each is shaded by how square-on it is, which is what gives the cube its
    form on a panel with no lighting model.
    """
    rx, ry, rz = (math.radians(a) for a in angles)
    half = 0.5
    try:
        pips = pip_values(int(detail))
    except (TypeError, ValueError):
        pips = [1, 2, 3, 4, 5, 6]
    scale = size * scale_factor

    for index, (normal, u_axis, v_axis) in enumerate(FACES):
        turned_normal = _rotate(normal, rx, ry, rz)
        facing = -turned_normal[2]
        if facing <= 0.04:          # edge-on or pointing away
            continue

        def to_screen(fx: float, fy: float):
            point = tuple(normal[i] * half + u_axis[i] * fx + v_axis[i] * fy
                          for i in range(3))
            return _project(_rotate(point, rx, ry, rz), cx, cy, scale)

        corners = [to_screen(-half, -half), to_screen(half, -half),
                   to_screen(half, half), to_screen(-half, half)]
        # A side turned away from the light is darker, so the cube reads as a
        # solid rather than a flat outline.
        shade = 0.35 + 0.65 * facing
        edge = tuple(int(c * shade) for c in colour)
        dice_faces._poly(draw, corners, fill=void, outline=edge,
                         width=max(1, int(size * 0.03)))

        symbol = sides[index] if index < len(sides) else "pip"
        face_detail = pips[index] if symbol == "pip" else detail
        for points, role in dice_faces.face_geometry(symbol, face_detail):
            projected = [to_screen(px, py) for px, py in points]
            dice_faces._poly(draw, projected,
                             fill=edge if role == "ink" else void)


def supports(kind: str) -> bool:
    """Whether this kind of dice has symbols to carry on a cube.

    A D66 or a D20 shows a number, and a number on the side of a tumbling cube
    at this size is unreadable, so those keep the flat treatment.
    """
    return kind in _SIDES
