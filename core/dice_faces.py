"""The symbols moulded on Necromunda's dice, drawn for the 240x240 eye.

Necromunda's dice do not show numbers. An Injury dice shows a cross, a
splintered burst or a skull; a Firepower dice shows bullet holes and an ammo
symbol; a Scatter dice shows arrows and a crosshair. Printing the words instead
("Serious Injury") wastes a round 240px panel and reads slowly across a table,
so the eye draws the face the player would see on the dice in their hand.

Each symbol is defined once, as GEOMETRY: an ordered list of polygons in a unit
face square running -0.5 to 0.5, each marked as ink or as a void punched out of
what is already there. Geometry rather than drawing calls, because the same
symbol has to be drawn two ways -- flat on the result, and projected onto the
side of a tumbling cube (``core.dice3d``). A circle drawn by ``ImageDraw.ellipse``
cannot be turned in three dimensions; a ring of points can.

Nothing here touches display state, so the faces can be rendered and checked
without the panel.

Shapes are built for legibility at roughly 40-70px inside a 146px aperture:
solid silhouettes, no hairlines, nothing that depends on colour to be read.
"""
from __future__ import annotations

import math

# The symbol names dice.face_symbol() produces.
SYMBOLS = (
    "cross", "starburst", "skull",      # Injury
    "holes1", "holes2", "holes3", "ammo",  # Firepower
    "crosshair", "arrow",               # Scatter
    "pip",
)


_CIRCLE_STEPS = 22


def _poly(draw, points, fill=None, outline=None, width=1):
    draw.polygon([(round(x), round(y)) for x, y in points],
                 fill=fill, outline=outline, width=width)


def _rotate(points, cx, cy, degrees):
    rad = math.radians(degrees)
    cos_a, sin_a = math.cos(rad), math.sin(rad)
    return [(cx + (x - cx) * cos_a - (y - cy) * sin_a,
             cy + (x - cx) * sin_a + (y - cy) * cos_a) for x, y in points]


def _ellipse(cx, cy, rx, ry, steps: int = _CIRCLE_STEPS):
    return [(cx + rx * math.cos(2 * math.pi * i / steps),
             cy + ry * math.sin(2 * math.pi * i / steps)) for i in range(steps)]


def _circle(cx, cy, r, steps: int = _CIRCLE_STEPS):
    return _ellipse(cx, cy, r, r, steps)


def _rect(x0, y0, x1, y1):
    return [(x0, y0), (x1, y0), (x1, y1), (x0, y1)]


def _bar(x0, y0, x1, y1, width):
    """A thick line as a quad, so it survives projection like everything else."""
    dx, dy = x1 - x0, y1 - y0
    length = math.hypot(dx, dy) or 1.0
    nx, ny = -dy / length * width / 2, dx / length * width / 2
    return [(x0 + nx, y0 + ny), (x1 + nx, y1 + ny),
            (x1 - nx, y1 - ny), (x0 - nx, y0 - ny)]


def _torn_ring(cx, cy, radius, teeth: int = 10, depth: float = 0.16):
    """A bullet hole: a ragged rim with the middle punched out.

    A plain circle reads as a pip at this size, but deep teeth read as a star
    and collide with the Serious Injury burst. Shallow tearing plus a void in
    the middle is what makes it read as a hole punched THROUGH something.
    """
    rim = []
    for i in range(teeth * 2):
        angle = math.pi * i / teeth
        r = radius * (1.0 - depth * (i % 2))
        rim.append((cx + r * math.cos(angle), cy + r * math.sin(angle)))
    return [(rim, "ink"), (_circle(cx, cy, radius * 0.42), "void")]


def _geom_cross():
    """Injured: a thick cross with a droplet punched out of its heart."""
    arm, bar, drop = 0.50, 0.19, 0.15
    shape = [(-bar, -arm), (bar, -arm), (bar, -bar), (arm, -bar), (arm, bar),
             (bar, bar), (bar, arm), (-bar, arm), (-bar, bar), (-arm, bar),
             (-arm, -bar), (-bar, -bar)]
    return [
        (shape, "ink"),
        (_ellipse(0.0, drop * 0.35, drop, drop * 0.95), "void"),
        ([(0.0, -drop * 1.9), (-drop * 0.95, drop * 0.3), (drop * 0.95, drop * 0.3)],
         "void"),
    ]


def _geom_starburst(spikes: int = 6):
    """Serious Injury: a splintered impact burst.

    Few and fat, not many and fine: thin spikes read as a sparkle and, worse,
    look like the Firepower dice's torn bullet holes at a glance.
    """
    outer, spread = 0.50, 0.62
    out = []
    for i in range(spikes):
        angle = 2 * math.pi * i / spikes - math.pi / 2
        length = outer if i % 2 == 0 else outer * 0.74
        tip = (length * math.cos(angle), length * math.sin(angle))
        left = (outer * 0.34 * math.cos(angle - spread),
                outer * 0.34 * math.sin(angle - spread))
        right = (outer * 0.34 * math.cos(angle + spread),
                 outer * 0.34 * math.sin(angle + spread))
        out.append(([tip, left, right], "ink"))
    out.append((_circle(0.0, 0.0, 0.22), "ink"))
    return out


def _geom_skull():
    """Out of Action."""
    half = 0.40
    jaw_w, jaw_top, jaw_h = half * 0.58, half * 0.46, half * 0.52
    out = [
        (_ellipse(0.0, -half * 0.18, half, half * 0.90), "ink"),
        (_rect(-jaw_w, jaw_top, jaw_w, jaw_top + jaw_h), "ink"),
    ]
    for sign in (-1, 1):
        out.append((_ellipse(sign * half * 0.40, -half * 0.12,
                             half * 0.30, half * 0.24), "void"))
    nose = half * 0.15
    out.append(([(0.0, half * 0.08), (-nose, half * 0.40), (nose, half * 0.40)],
                "void"))
    for sign in (-1, 0, 1):
        tx = sign * half * 0.30
        out.append((_bar(tx, jaw_top, tx, jaw_top + jaw_h, 0.035), "void"))
    return out


def _geom_holes(count: int = 1):
    """Firepower: one, two or three bullet holes, as the dice shows them."""
    count = max(1, min(3, int(count)))
    if count == 1:
        return _torn_ring(0.0, 0.0, 0.30)
    if count == 2:
        out = []
        for sign in (-1, 1):
            out += _torn_ring(sign * 0.24, sign * 0.12, 0.22)
        return out
    out = []
    for angle in (-90, 30, 150):
        rad = math.radians(angle)
        out += _torn_ring(0.27 * math.cos(rad), 0.27 * math.sin(rad), 0.19)
    return out


def _geom_ammo():
    """Firepower: the ammo symbol, drawn as a shell casing."""
    body_w, body_h = 0.20, 0.30
    return [
        (_rect(-body_w, -body_h * 0.2, body_w, body_h * 1.3), "ink"),
        ([(0.0, -0.50), (-body_w, -body_h * 0.1), (body_w, -body_h * 0.1)], "ink"),
        (_bar(-body_w, body_h * 0.95, body_w, body_h * 0.95, 0.045), "void"),
    ]


def _geom_crosshair():
    """Scatter: the Hit face."""
    r, line_w = 0.38, 0.07
    out = [(_circle(0.0, 0.0, r + line_w / 2), "ink"),
           (_circle(0.0, 0.0, r - line_w / 2), "void")]
    for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1)):
        out.append((_bar(dx * r * 0.55, dy * r * 0.55,
                         dx * r * 1.42, dy * r * 1.42, line_w), "ink"))
    out.append((_circle(0.0, 0.0, 0.09), "ink"))
    return out


def _geom_arrow(degrees: float = 0.0):
    """Scatter: a direction arrow, pointing ``degrees`` clockwise from up."""
    head, shaft = 0.26, 0.11
    points = [(0.0, -0.48), (-head, -0.06), (-shaft, -0.06), (-shaft, 0.46),
              (shaft, 0.46), (shaft, -0.06), (head, -0.06)]
    return [(_rotate(points, 0.0, 0.0, degrees), "ink")]


def _geom_pips(value: int = 1):
    """A plain D6 face, for the rolls that use ordinary dice."""
    value = max(1, min(6, int(value)))
    step, r = 0.26, 0.085
    layouts = {
        1: [(0, 0)],
        2: [(-1, -1), (1, 1)],
        3: [(-1, -1), (0, 0), (1, 1)],
        4: [(-1, -1), (1, -1), (-1, 1), (1, 1)],
        5: [(-1, -1), (1, -1), (0, 0), (-1, 1), (1, 1)],
        6: [(-1, -1), (1, -1), (-1, 0), (1, 0), (-1, 1), (1, 1)],
    }
    return [(_circle(gx * step, gy * step, r), "ink") for gx, gy in layouts[value]]


def face_geometry(symbol: str, detail=None) -> list:
    """The polygons for one face, in a unit square running -0.5 to 0.5.

    Each entry is (points, role), in draw order; "void" punches back out of the
    ink already laid down. Unknown symbols fall back to a single pip rather than
    nothing, so a face this module has not been taught still shows that a dice
    was rolled.
    """
    symbol = (symbol or "").strip()
    if symbol == "cross":
        return _geom_cross()
    if symbol == "starburst":
        return _geom_starburst()
    if symbol == "skull":
        return _geom_skull()
    if symbol.startswith("holes"):
        return _geom_holes(int(symbol[5:] or 1))
    if symbol == "ammo":
        return _geom_ammo()
    if symbol == "crosshair":
        return _geom_crosshair()
    if symbol == "arrow":
        try:
            bearing = float(detail)
        except (TypeError, ValueError):
            bearing = 0.0
        # A scatter dice is read at whatever rotation it landed in, so the
        # bearing is any angle, not one of four headings.
        return _geom_arrow(bearing)
    if symbol == "pip":
        return _geom_pips(int(detail or 1))
    return _geom_pips(1)


def draw_face(draw, symbol: str, cx: float, cy: float, size: float, colour,
              detail=None, void=(0, 0, 0)) -> None:
    """Draw one face flat, by the symbol name ``dice.face_symbol()`` returns."""
    for points, role in face_geometry(symbol, detail):
        _poly(draw, [(cx + px * size, cy + py * size) for px, py in points],
              fill=colour if role == "ink" else void)


def draw_die_body(draw, cx, cy, size, colour, fill=(0, 0, 0), width: int = 3):
    """The rounded cube outline a face is shown on."""
    half = size * 0.56
    draw.rounded_rectangle([cx - half, cy - half, cx + half, cy + half],
                           radius=max(3, int(size * 0.17)), fill=fill,
                           outline=colour, width=width)


# What a dice of each kind can show, for the blur of faces while it tumbles.
TUMBLE_POOL: dict[str, tuple[str, ...]] = {
    "injury": ("cross", "starburst", "skull"),
    "firepower": ("holes1", "holes2", "holes3", "ammo"),
    "scatter": ("crosshair", "arrow"),
}

# How many dice are drawn before the rest become a count. Seven 50px dice do
# not fit a 146px aperture legibly, and a wall of tiny symbols says less than
# six clear ones and a number.
MAX_DRAWN = 6

# (rows, die size, pitch factor, draw the cube outline) for each number of
# dice. Sizes are the largest that keep every corner inside the aperture, found
# by measuring the corners rather than guessed -- a dice that overflows is cut
# by the iris mask and loses the part that carries its meaning.
#
# Past four, the cube outline is dropped and the symbols are drawn bare. Fitting
# six outlined dice means shrinking them to 34px, where the symbol inside is too
# small to read; without the outline the same six fit at 42px.
_LAYOUTS: dict[int, tuple[tuple[int, ...], float, float, bool]] = {
    1: ((1,), 88.0, 1.18, True),
    2: ((2,), 56.0, 1.18, True),
    3: ((2, 1), 44.0, 1.18, True),
    4: ((2, 2), 44.0, 1.18, True),
    5: ((3, 2), 42.0, 1.05, False),
    6: ((3, 3), 42.0, 1.05, False),
}


def layout(count: int, cx: float = 120.0,
           cy: float = 120.0) -> list[tuple[float, float, float, bool]]:
    """Positions, size and whether to outline, for ``count`` dice in the aperture.

    Returns (x, y, size, with_body) per dice. One dice fills the eye; more are
    stacked in rows and shrunk to fit.
    """
    count = max(1, min(MAX_DRAWN, int(count)))
    rows, size, pitch_factor, with_body = _LAYOUTS[count]
    pitch = size * pitch_factor
    out: list[tuple[float, float, float, bool]] = []
    top = cy - (len(rows) - 1) * pitch / 2
    for row_index, row_count in enumerate(rows):
        row_y = top + row_index * pitch
        left = cx - (row_count - 1) * pitch / 2
        for col in range(row_count):
            out.append((left + col * pitch, row_y, size, with_body))
    return out
