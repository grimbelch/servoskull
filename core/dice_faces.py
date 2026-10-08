"""The symbols moulded on Necromunda's dice, drawn for the 240x240 eye.

Necromunda's dice do not show numbers. An Injury dice shows a cross, a
splintered burst or a skull; a Firepower dice shows bullet holes and an ammo
symbol; a Scatter dice shows arrows and a crosshair. Printing the words instead
("Serious Injury") wastes a round 240px panel and reads slowly across a table,
so the eye draws the face the player would see on the dice in their hand.

Every function here is pure drawing against a Pillow ImageDraw, with no display
state, so the faces can be rendered and checked without the panel.

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


def _poly(draw, points, fill=None, outline=None, width=1):
    draw.polygon([(round(x), round(y)) for x, y in points],
                 fill=fill, outline=outline, width=width)


def _rotate(points, cx, cy, degrees):
    rad = math.radians(degrees)
    cos_a, sin_a = math.cos(rad), math.sin(rad)
    return [(cx + (x - cx) * cos_a - (y - cy) * sin_a,
             cy + (x - cx) * sin_a + (y - cy) * cos_a) for x, y in points]


def _jagged_circle(draw, cx, cy, radius, colour, teeth: int = 10, depth: float = 0.16):
    """A torn bullet hole: a ring with a ragged rim and a punched-out centre.

    A plain circle reads as a pip at this size, but deep teeth read as a star
    and collide with the Serious Injury burst. Shallow tearing plus a void in
    the middle is what makes it read as a hole punched THROUGH something.
    """
    points = []
    for i in range(teeth * 2):
        angle = math.pi * i / teeth
        r = radius * (1.0 - depth * (i % 2))
        points.append((cx + r * math.cos(angle), cy + r * math.sin(angle)))
    _poly(draw, points, fill=colour)
    void = radius * 0.42
    draw.ellipse([cx - void, cy - void, cx + void, cy + void], fill=(0, 0, 0))


def draw_cross(draw, cx, cy, size, colour):
    """Injured: a thick cross with a droplet at its heart."""
    arm = size * 0.5
    bar = size * 0.19
    _poly(draw, [(cx - bar, cy - arm), (cx + bar, cy - arm), (cx + bar, cy - bar),
                 (cx + arm, cy - bar), (cx + arm, cy + bar), (cx + bar, cy + bar),
                 (cx + bar, cy + arm), (cx - bar, cy + arm), (cx - bar, cy + bar),
                 (cx - arm, cy + bar), (cx - arm, cy - bar), (cx - bar, cy - bar)],
          fill=colour)
    # The droplet is punched out of the cross, so it has to be the background.
    drop = size * 0.15
    draw.ellipse([cx - drop, cy - drop * 0.6, cx + drop, cy + drop * 1.3], fill=(0, 0, 0))
    _poly(draw, [(cx, cy - drop * 1.9), (cx - drop * 0.95, cy + drop * 0.3),
                 (cx + drop * 0.95, cy + drop * 0.3)], fill=(0, 0, 0))


def draw_starburst(draw, cx, cy, size, colour, spikes: int = 6):
    """Serious Injury: a splintered impact burst.

    Few and fat, not many and fine: thin spikes read as a sparkle and, worse,
    look like the Firepower dice's torn bullet holes at a glance. The two
    symbols have to be separable across a table.
    """
    outer = size * 0.50
    spread = 0.62
    for i in range(spikes):
        angle = 2 * math.pi * i / spikes - math.pi / 2
        length = outer if i % 2 == 0 else outer * 0.74
        tip = (cx + length * math.cos(angle), cy + length * math.sin(angle))
        left = (cx + outer * 0.34 * math.cos(angle - spread),
                cy + outer * 0.34 * math.sin(angle - spread))
        right = (cx + outer * 0.34 * math.cos(angle + spread),
                 cy + outer * 0.34 * math.sin(angle + spread))
        _poly(draw, [tip, left, right], fill=colour)
    core = size * 0.22
    draw.ellipse([cx - core, cy - core, cx + core, cy + core], fill=colour)


def draw_skull(draw, cx, cy, size, colour):
    """Out of Action."""
    half = size * 0.40
    draw.ellipse([cx - half, cy - half * 1.08, cx + half, cy + half * 0.72], fill=colour)
    jaw_w, jaw_top, jaw_h = half * 0.58, cy + half * 0.46, half * 0.52
    draw.rounded_rectangle([cx - jaw_w, jaw_top, cx + jaw_w, jaw_top + jaw_h],
                           radius=max(2, int(size * 0.07)), fill=colour)
    # Sockets and nose are voids, so they are cut in the background colour.
    eye_r = half * 0.30
    for sign in (-1, 1):
        ex = cx + sign * half * 0.40
        draw.ellipse([ex - eye_r, cy - half * 0.36, ex + eye_r, cy + half * 0.12],
                     fill=(0, 0, 0))
    nose = half * 0.15
    _poly(draw, [(cx, cy + half * 0.08), (cx - nose, cy + half * 0.40),
                 (cx + nose, cy + half * 0.40)], fill=(0, 0, 0))
    for sign in (-1, 0, 1):
        tx = cx + sign * half * 0.30
        draw.line([(tx, jaw_top), (tx, jaw_top + jaw_h)], fill=(0, 0, 0),
                  width=max(1, int(size * 0.035)))


def draw_holes(draw, cx, cy, size, colour, count: int = 1):
    """Firepower: one, two or three bullet holes, as the die shows them."""
    count = max(1, min(3, int(count)))
    if count == 1:
        _jagged_circle(draw, cx, cy, size * 0.30, colour)
        return
    if count == 2:
        offset, radius = size * 0.24, size * 0.22
        _jagged_circle(draw, cx - offset, cy - offset * 0.5, radius, colour)
        _jagged_circle(draw, cx + offset, cy + offset * 0.5, radius, colour)
        return
    radius = size * 0.19
    for angle in (-90, 30, 150):
        rad = math.radians(angle)
        _jagged_circle(draw, cx + size * 0.27 * math.cos(rad),
                       cy + size * 0.27 * math.sin(rad), radius, colour)


def draw_ammo(draw, cx, cy, size, colour):
    """Firepower: the ammo symbol, drawn as a shell casing."""
    body_w, body_h = size * 0.20, size * 0.30
    draw.rounded_rectangle([cx - body_w, cy - body_h * 0.2, cx + body_w, cy + body_h * 1.3],
                           radius=max(2, int(size * 0.05)), fill=colour)
    _poly(draw, [(cx, cy - size * 0.50), (cx - body_w, cy - body_h * 0.1),
                 (cx + body_w, cy - body_h * 0.1)], fill=colour)
    draw.line([(cx - body_w, cy + body_h * 0.95), (cx + body_w, cy + body_h * 0.95)],
              fill=(0, 0, 0), width=max(1, int(size * 0.045)))


def draw_crosshair(draw, cx, cy, size, colour):
    """Scatter: the Hit face."""
    r = size * 0.38
    line_w = max(2, int(size * 0.07))
    draw.ellipse([cx - r, cy - r, cx + r, cy + r], outline=colour, width=line_w)
    for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1)):
        draw.line([(cx + dx * r * 0.55, cy + dy * r * 0.55),
                   (cx + dx * r * 1.42, cy + dy * r * 1.42)], fill=colour, width=line_w)
    dot = size * 0.09
    draw.ellipse([cx - dot, cy - dot, cx + dot, cy + dot], fill=colour)


def draw_arrow(draw, cx, cy, size, colour, degrees: float = 0.0):
    """Scatter: a direction arrow, pointing ``degrees`` clockwise from up."""
    head, shaft = size * 0.26, size * 0.11
    points = [(cx, cy - size * 0.48), (cx - head, cy - size * 0.06),
              (cx - shaft, cy - size * 0.06), (cx - shaft, cy + size * 0.46),
              (cx + shaft, cy + size * 0.46), (cx + shaft, cy - size * 0.06),
              (cx + head, cy - size * 0.06)]
    _poly(draw, _rotate(points, cx, cy, degrees), fill=colour)


def draw_pips(draw, cx, cy, size, colour, value: int = 1):
    """A plain D6 face, for the rolls that use ordinary dice."""
    value = max(1, min(6, int(value)))
    step, r = size * 0.26, max(2, size * 0.085)
    layouts = {
        1: [(0, 0)],
        2: [(-1, -1), (1, 1)],
        3: [(-1, -1), (0, 0), (1, 1)],
        4: [(-1, -1), (1, -1), (-1, 1), (1, 1)],
        5: [(-1, -1), (1, -1), (0, 0), (-1, 1), (1, 1)],
        6: [(-1, -1), (1, -1), (-1, 0), (1, 0), (-1, 1), (1, 1)],
    }
    for gx, gy in layouts[value]:
        px, py = cx + gx * step, cy + gy * step
        draw.ellipse([px - r, py - r, px + r, py + r], fill=colour)


def draw_face(draw, symbol: str, cx: float, cy: float, size: float, colour,
              detail=None) -> None:
    """Draw one die face by the symbol name ``dice.face_symbol()`` returns.

    Unknown symbols fall back to a single pip rather than drawing nothing, so a
    face this module has not been taught still shows that a dice was rolled.
    """
    symbol = (symbol or "").strip()
    if symbol == "cross":
        draw_cross(draw, cx, cy, size, colour)
    elif symbol == "starburst":
        draw_starburst(draw, cx, cy, size, colour)
    elif symbol == "skull":
        draw_skull(draw, cx, cy, size, colour)
    elif symbol.startswith("holes"):
        draw_holes(draw, cx, cy, size, colour, int(symbol[5:] or 1))
    elif symbol == "ammo":
        draw_ammo(draw, cx, cy, size, colour)
    elif symbol == "crosshair":
        draw_crosshair(draw, cx, cy, size, colour)
    elif symbol == "arrow":
        # A scatter dice is read at whatever rotation it landed in, so the
        # bearing is any angle, not one of four headings.
        try:
            bearing = float(detail)
        except (TypeError, ValueError):
            bearing = 0.0
        draw_arrow(draw, cx, cy, size, colour, bearing)
    elif symbol == "pip":
        draw_pips(draw, cx, cy, size, colour, int(detail or 1))
    else:
        draw_pips(draw, cx, cy, size, colour, 1)


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
