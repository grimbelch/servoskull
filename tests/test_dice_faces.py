"""The Necromunda dice faces drawn on the eye (run: python -m pytest tests).

Necromunda's dice carry symbols, not numbers, so the eye draws the face rather
than spelling the result out. These check the drawing is actually visible, that
nothing is laid out where the round aperture would cut it off, and that a rolled
result reaches the screen as the matching symbol.
"""

import math

import pytest
from PIL import Image, ImageDraw

from core import dice_faces
from games.necromunda import dice

APERTURE = 73          # the cog's central opening, from core.display
CENTRE = (120.0, 120.0)
INK = (0, 255, 120)


def render(symbol, size=80, detail=None):
    img = Image.new("RGB", (240, 240), (0, 0, 0))
    dice_faces.draw_face(ImageDraw.Draw(img), symbol, 120, 120, size, INK, detail)
    return img


def lit_pixels(img):
    px = img.load()
    return sum(1 for x in range(240) for y in range(240) if px[x, y] != (0, 0, 0))


def lit_points(img):
    px = img.load()
    return [(x, y) for x in range(240) for y in range(240) if px[x, y] != (0, 0, 0)]


# ── the faces draw something legible ──────────────────────────────────────────

@pytest.mark.parametrize("symbol", dice_faces.SYMBOLS)
def test_every_symbol_draws_something(symbol):
    """A face that draws nothing silently turns a roll into a blank eye."""
    # A single pip is the smallest legitimate face, at about 150 pixels.
    assert lit_pixels(render(symbol)) > 100


@pytest.mark.parametrize("symbol", dice_faces.SYMBOLS)
def test_a_face_stays_inside_the_aperture(symbol):
    """Anything outside the iris mask is cut off by the eye's opening."""
    img = render(symbol, size=88)
    for x, y in ((x, y) for x in range(240) for y in range(240)):
        if img.getpixel((x, y)) != (0, 0, 0):
            assert math.hypot(x - 120, y - 120) <= APERTURE


def test_a_bullet_hole_is_a_hole_and_a_burst_is_solid():
    """Serious Injury and a bullet hole must not read as the same mark.

    They were nearly identical at first -- a fine-spiked burst and a deeply
    toothed hole, both reading as a star. What separates them is that a hole is
    punched THROUGH: its middle is empty, and the burst's is solid.
    """
    assert render("holes1").getpixel((120, 120)) == (0, 0, 0)
    assert render("starburst").getpixel((120, 120)) != (0, 0, 0)
    assert render("holes2").getpixel((120, 120)) == (0, 0, 0)


@pytest.mark.parametrize("bearing", [0, 37, 90, 126, 180, 214, 270, 315])
def test_an_arrow_points_along_its_bearing(bearing):
    """A scatter dice is read at the rotation it landed in, so any angle.

    Measured at the tip -- the furthest lit pixel from the centre -- because the
    arrow is nearly balanced about its middle and its centre of mass barely
    moves as it turns.
    """
    points = lit_points(render("arrow", size=88, detail=bearing))
    tip = max(points, key=lambda p: math.hypot(p[0] - 120, p[1] - 120))
    # Screen y grows downward, and a bearing is clockwise from straight up.
    angle = math.degrees(math.atan2(tip[0] - 120, 120 - tip[1])) % 360
    assert min(abs(angle - bearing), 360 - abs(angle - bearing)) < 12


@pytest.mark.parametrize("value", [1, 2, 3, 4, 5, 6])
def test_a_pip_face_shows_its_own_number_of_pips(value):
    smaller = lit_pixels(render("pip", detail=value))
    bigger = lit_pixels(render("pip", detail=min(6, value + 1)))
    assert smaller <= bigger


def test_an_unknown_symbol_still_shows_that_a_dice_was_rolled():
    assert lit_pixels(render("no-such-face")) > 100


# ── layout ────────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("count", [1, 2, 3, 4, 5, 6])
def test_every_dice_fits_the_round_aperture(count):
    """A dice that overflows is clipped by the iris and loses its meaning."""
    for x, y, size, with_body in dice_faces.layout(count):
        if with_body:
            half = size * 0.56
            corners = [(x + dx, y + dy) for dx in (half, -half) for dy in (half, -half)]
            assert all(math.hypot(cx - 120, cy - 120) <= APERTURE for cx, cy in corners)
        else:
            assert math.hypot(x - 120, y - 120) + size * 0.52 <= APERTURE


@pytest.mark.parametrize("count", [1, 2, 3, 4, 5, 6])
def test_layout_places_one_slot_per_dice(count):
    assert len(dice_faces.layout(count)) == count


def test_more_dice_than_fit_are_capped():
    assert len(dice_faces.layout(40)) == dice_faces.MAX_DRAWN


def test_dice_do_not_overlap_each_other():
    for count in (2, 3, 4, 5, 6):
        slots = dice_faces.layout(count)
        for i, (x1, y1, s1, _b) in enumerate(slots):
            for x2, y2, _s2, _b2 in slots[i + 1:]:
                assert math.hypot(x1 - x2, y1 - y2) >= s1 * 1.0


# ── a rolled result reaches the screen ────────────────────────────────────────

@pytest.mark.parametrize("kind,faces", [
    ("injury", dice.INJURY_FACES),
    ("scatter", dice.SCATTER_FACES),
])
def test_every_face_a_dice_can_land_on_has_art(kind, faces):
    """A face with no drawing would show as a blank or a fallback pip."""
    for face in set(faces):
        symbol = dice.face_symbol(kind, face)
        assert symbol in dice_faces.SYMBOLS
        # A single pip is the smallest legitimate face, at about 150 pixels.
    assert lit_pixels(render(symbol)) > 100


def test_firepower_faces_all_have_art():
    for shots, ammo in dice.FIREPOWER_FACES:
        symbol = dice.face_symbol("firepower", "ammo" if ammo else str(shots))
        assert symbol in dice_faces.SYMBOLS


# ── the roll animation ────────────────────────────────────────────────────────

def _frame(elapsed, faces=("skull", "cross", "starburst"), kind="injury"):
    from core import display
    display._mood_rgb = INK
    bezel = Image.new("RGB", (240, 240), (0, 0, 0))
    mask = display._make_iris_mask()
    return display._render_die_frame(bezel, mask, elapsed, "9", kind, faces,
                                     (None,) * len(faces), 0)


def _differing(a, b):
    pa, pb = a.load(), b.load()
    return sum(1 for x in range(240) for y in range(240) if pa[x, y] != pb[x, y])


def test_the_dice_are_thrown_rather_than_flickering_in_place():
    """Mid-flight the dice are somewhere else entirely, not on their slots.

    The first version jittered them on the spot and swapped the face, which
    reads as a slot machine rather than a roll.
    """
    assert _differing(_frame(0.30), _frame(2.0)) > 2500


def test_the_dice_come_to_rest_on_their_slots():
    """Once landed, every frame shows the same upright arrangement."""
    assert _differing(_frame(1.8), _frame(2.6)) < 1400  # only the sweep moves


def test_a_dice_lands_upright_however_far_it_flew():
    """Each dice turns a whole number of times, so it cannot land on its corner."""
    from core import display
    for turns in display._DIE_TURNS:
        landed = turns * 360.0 * (1.0 - (1.0 - 1.0) ** 3)
        assert landed % 360 == pytest.approx(0.0)


def test_a_turned_dice_is_actually_drawn_turned():
    """Rotation has to reach the pixels, not just the maths.

    Measured on the skull, which is the one face with a clear top and bottom:
    its mass sits above centre upright and below centre upside down. Comparing
    images outright would fail on nothing worse than the smoothing a rotation
    leaves along every edge.
    """
    from core import display

    def mass_height(angle):
        img = Image.new("RGB", (240, 240), (0, 0, 0))
        display._draw_one_die(ImageDraw.Draw(img), img, 120, 120, 80, INK,
                              "skull", None, False, angle)
        points = lit_points(img)
        return sum(p[1] for p in points) / len(points)

    assert mass_height(0.0) < 119.0      # cranium up
    assert mass_height(180.0) > 121.0    # turned over
    # A whole turn puts it back where it started.
    assert mass_height(360.0) == pytest.approx(mass_height(0.0), abs=1.5)


def test_the_throw_overshoots_and_settles():
    """The landing bounces: the dice pass the slot and come back to it."""
    from core import display
    assert display._ease_out_back(0.0) == pytest.approx(0.0)
    assert display._ease_out_back(1.0) == pytest.approx(1.0)
    peak = max(display._ease_out_back(t / 100) for t in range(101))
    assert peak > 1.0


def test_the_eye_is_not_blank_when_a_roll_starts():
    """Dice thrown from too far out leave the eye empty, which reads as a fault."""
    assert lit_pixels(_frame(0.05)) > 300
