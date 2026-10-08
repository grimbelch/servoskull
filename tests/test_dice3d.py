"""Necromunda dice drawn as real cubes (run: python -m pytest tests).

The cube carries the six faces the dice really has and turns in space, so these
check that it shows the right sides, hides the ones facing away, and comes to
rest on the face that was actually rolled.
"""

import math

import pytest
from PIL import Image, ImageDraw

from core import dice3d
from games.necromunda import dice

INK = (0, 255, 120)
APERTURE = 73


def render(sides, angles=(0.0, 0.0, 0.0), size=88, detail=None,
           scale=dice3d.SCALE_TUMBLING):
    img = Image.new("RGB", (240, 240), (0, 0, 0))
    dice3d.draw_die(ImageDraw.Draw(img), 120, 120, size, INK, (0, 0, 0),
                    sides, detail, angles, scale)
    return img


def lit(img):
    px = img.load()
    return [(x, y) for x in range(240) for y in range(240) if px[x, y] != (0, 0, 0)]


def visible_faces(angles):
    rx, ry, rz = (math.radians(a) for a in angles)
    return sum(1 for normal, _u, _v in dice3d.FACES
               if -dice3d._rotate(normal, rx, ry, rz)[2] > 0.04)


# ── which faces a dice carries ────────────────────────────────────────────────

def test_a_dice_carries_its_real_distribution_of_faces():
    """An Injury dice is two Injured, three Serious Injury and one Out of Action.

    The cube shows whichever sides face the viewer as it turns, so they have to
    be the sides the dice actually has.
    """
    sides = dice3d.sides_for("injury", "cross")
    assert len(sides) == 6
    assert sides.count("cross") == 2
    assert sides.count("starburst") == 3
    assert sides.count("skull") == 1


def test_the_rolled_face_is_the_one_at_the_front():
    for kind, landed in (("injury", "skull"), ("firepower", "ammo"),
                         ("scatter", "arrow"), ("d6", "pip")):
        assert dice3d.sides_for(kind, landed)[0] == landed


def test_every_face_an_injury_dice_can_land_on_can_be_put_in_front():
    for face in set(dice.INJURY_FACES):
        symbol = dice.face_symbol("injury", face)
        sides = dice3d.sides_for("injury", symbol)
        assert sides[0] == symbol and len(sides) == 6


def test_numbered_dice_keep_the_flat_treatment():
    """A number on the side of a tumbling cube is unreadable at this size."""
    assert dice3d.supports("injury")
    assert dice3d.supports("d6")
    assert not dice3d.supports("num")


# ── turning in space ──────────────────────────────────────────────────────────

def test_only_the_sides_facing_the_viewer_are_drawn():
    """A cube has at most three sides toward us, never more."""
    for ax in range(0, 360, 29):
        for ay in range(0, 360, 31):
            assert visible_faces((ax, ay, 0)) <= 3


def test_square_on_shows_exactly_one_side():
    assert visible_faces((0, 0, 0)) == 1
    assert visible_faces((0, 0, 47)) == 1   # spun in its own plane, still one


def test_turning_reveals_more_of_the_cube():
    """Tilted, the dice shows its sides; that is what makes it look solid."""
    assert visible_faces((34, 38, 0)) == 3
    sides = dice3d.sides_for("injury", "skull")
    tilted = len(lit(render(sides, (34, 38, 0))))
    square_on = len(lit(render(sides, (0, 0, 0))))
    assert tilted > square_on


def test_a_turning_cube_never_leaves_the_aperture():
    """Clipped by the iris, a dice loses the part that carries its meaning."""
    sides = dice3d.sides_for("injury", "skull")
    for ax in (0, 25, 45, 70):
        for ay in (0, 35, 55, 90):
            for x, y in lit(render(sides, (ax, ay, 20))):
                assert math.hypot(x - 120, y - 120) <= APERTURE


def test_the_landed_cube_matches_the_flat_dice_it_becomes():
    """Square-on they are the same silhouette, so the changeover is invisible."""
    from core import dice_faces
    points = lit(render(dice3d.sides_for("injury", "skull"), (0, 0, 0),
                        scale=dice3d.SCALE_LANDED))
    reach = max(math.hypot(x - 120, y - 120) for x, y in points)
    flat_corner = 88 * 0.56 * math.sqrt(2)
    assert reach == pytest.approx(flat_corner, abs=4.0)
    assert dice_faces.layout(1)[0][2] == 88.0


def test_the_front_face_shows_the_rolled_symbol():
    """Square-on, the cube shows the face that was rolled and nothing else."""
    skull = render(dice3d.sides_for("injury", "skull"), (0, 0, 0))
    cross = render(dice3d.sides_for("injury", "cross"), (0, 0, 0))
    differing = sum(1 for a, b in zip(lit(skull), lit(cross)) if a != b)
    assert differing > 100
