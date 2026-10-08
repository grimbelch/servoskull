"""Getting an image from the open internet onto a 240x240 panel.

_blit packs three channels by indexing arr[..., 0:3], so anything that is not RGB
either packs short or raises. A 240x240 frame is 115200 bytes; measured before the
fix, L, P, 1 and I;16 all packed to 480, LA raised IndexError, and CMYK packed to
the right size in the wrong colours. The live artwork search returns P and RGBA
images routinely (run: python -m pytest tests).
"""
import numpy as np
import pytest

from PIL import Image

display = pytest.importorskip("core.display")

FRAME_BYTES = 240 * 240 * 2


def _pack(img):
    """Exactly what _blit does once to_rgb has had its say."""
    img = display.to_rgb(img)
    arr = np.asarray(img, dtype=np.uint16)
    r = (arr[..., 0] & 0xF8) << 8
    g = (arr[..., 1] & 0xFC) << 3
    b = (arr[..., 2] & 0xF8) >> 3
    return (r | g | b).astype(">u2").tobytes()


@pytest.mark.parametrize("mode", ["RGB", "RGBA", "L", "P", "CMYK", "1", "LA", "I;16"])
def test_every_mode_packs_to_a_whole_frame(mode):
    assert len(_pack(Image.new(mode, (240, 240)))) == FRAME_BYTES


def test_an_rgb_image_is_passed_through_untouched():
    img = Image.new("RGB", (240, 240), (10, 20, 30))
    assert display.to_rgb(img) is img


def test_transparency_is_composited_onto_black_not_dropped():
    # A transparent PNG used to render as whatever sat in its colour channels.
    img = Image.new("RGBA", (10, 10), (255, 0, 0, 0))      # fully transparent red
    out = display.to_rgb(img)
    assert out.mode == "RGB"
    assert out.getpixel((0, 0)) == (0, 0, 0)


def test_a_partly_transparent_pixel_is_blended():
    img = Image.new("RGBA", (10, 10), (255, 255, 255, 128))
    r, g, b = display.to_rgb(img).getpixel((0, 0))
    assert 120 <= r <= 136 and r == g == b


def test_an_opaque_pixel_survives_the_composite():
    img = Image.new("RGBA", (10, 10), (12, 34, 56, 255))
    assert display.to_rgb(img).getpixel((0, 0)) == (12, 34, 56)


def test_a_palette_image_with_transparency_is_composited():
    img = Image.new("P", (10, 10))
    img.info["transparency"] = 0
    assert display.to_rgb(img).mode == "RGB"


def test_greyscale_becomes_three_equal_channels():
    img = Image.new("L", (4, 4), 90)
    assert display.to_rgb(img).getpixel((0, 0)) == (90, 90, 90)


# ── reporting what actually happened ──────────────────────────────────────────

def test_no_panel_means_no_success(monkeypatch):
    # display_art announced "successfully projected" for pictures that never
    # reached the panel, because this returned early and said nothing.
    monkeypatch.setattr(display, "_available", False)
    assert display.display_pil_image(Image.new("RGB", (240, 240))) is False


def test_a_panel_that_takes_the_image_says_so(monkeypatch):
    monkeypatch.setattr(display, "_available", True)
    monkeypatch.setattr(display, "_poke", lambda *a, **k: None)
    assert display.display_pil_image(Image.new("RGB", (480, 320))) is True
    assert display._custom_image.size == (240, 240)
    assert display._custom_image.mode == "RGB"


def test_a_broken_image_is_a_failure_not_an_exception(monkeypatch):
    monkeypatch.setattr(display, "_available", True)
    monkeypatch.setattr(display, "_poke", lambda *a, **k: None)
    assert display.display_pil_image("not an image at all") is False


def test_a_non_rgb_image_reaches_the_panel_as_rgb(monkeypatch):
    monkeypatch.setattr(display, "_available", True)
    monkeypatch.setattr(display, "_poke", lambda *a, **k: None)
    assert display.display_pil_image(Image.new("P", (300, 300))) is True
    assert display._custom_image.mode == "RGB"
