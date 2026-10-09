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


# ── high bit depth ────────────────────────────────────────────────────────────

def test_a_sixteen_bit_image_is_scaled_not_clipped():
    """convert("RGB") clips these. A 16-bit greyscale piece measured 100% pure
    white, mean 254 — which is what a "full white screen" looked like."""
    import numpy as np
    arr = np.linspace(0, 65535, 32 * 32).reshape(32, 32).astype(np.uint16)
    src = Image.fromarray(arr)
    assert src.mode.startswith("I")
    out = np.asarray(display.to_rgb(src))
    assert out.min() == 0 and out.max() == 255
    assert 100 < out.mean() < 155          # a gradient, not a white wall


def test_an_eight_bit_range_integer_image_keeps_its_tones():
    # Only values past 255 need rescaling; stretching an 8-bit-range image would
    # silently alter how it looks.
    src = Image.new("I", (8, 8), 128)
    assert display.to_rgb(src).getpixel((0, 0)) == (128, 128, 128)


def test_a_flat_high_bit_depth_image_does_not_divide_by_zero():
    import numpy as np
    src = Image.fromarray(np.full((8, 8), 40000, dtype=np.uint16))
    assert display.to_rgb(src).getpixel((0, 0)) == (0, 0, 0)


# ── what the panel will actually show ─────────────────────────────────────────

def test_fit_to_panel_gives_a_square_rgb_frame():
    out = display.fit_to_panel(Image.new("P", (900, 300)))
    assert out.size == (240, 240) and out.mode == "RGB"


def test_fit_to_panel_takes_the_middle():
    # A wide image: red at the edges, green in the middle. The panel shows green.
    img = Image.new("RGB", (900, 300), (255, 0, 0))
    img.paste(Image.new("RGB", (300, 300), (0, 255, 0)), (300, 0))
    assert display.fit_to_panel(img).getpixel((120, 120)) == (0, 255, 0)


# ── revealing a picture rather than dropping it on cropped ────────────────────

def test_the_reveal_source_is_scaled_to_the_fill_size():
    src = display._reveal_source(Image.new("RGB", (1258, 635), (40, 50, 60)))
    assert min(src.size) == 240
    assert src.mode == "RGB"


def test_at_the_start_the_whole_picture_is_inside_the_panel():
    import numpy as np
    # A wide piece, like the ones "40k ork" returns: a centre crop keeps about
    # half of it, which is how the subject became unidentifiable.
    src = display._reveal_source(Image.new("RGB", (1258, 635), (80, 90, 100)))
    frame = display._reveal_frame(src, 0.0)
    a = np.asarray(frame)
    rows = np.where(a.mean(axis=(1, 2)) > 2)[0]
    cols = np.where(a.mean(axis=(0, 2)) > 2)[0]
    pw = cols.max() - cols.min() + 1
    ph = rows.max() - rows.min() + 1
    assert pw == 240                                  # the long side just fits
    assert abs(pw / ph - 1258 / 635) < 0.05           # aspect ratio preserved
    assert (a.mean(axis=2) <= 2).mean() > 0.4         # letterboxed above and below


def test_at_the_end_it_fills_the_panel():
    import numpy as np
    src = display._reveal_source(Image.new("RGB", (1258, 635), (80, 90, 100)))
    a = np.asarray(display._reveal_frame(src, 1.0))
    assert (a.mean(axis=2) <= 2).mean() == 0.0        # no letterbox left


def test_a_tall_picture_reveals_the_same_way():
    import numpy as np
    src = display._reveal_source(Image.new("RGB", (635, 1258), (80, 90, 100)))
    a = np.asarray(display._reveal_frame(src, 0.0))
    rows = np.where(a.mean(axis=(1, 2)) > 2)[0]
    assert rows.max() - rows.min() + 1 == 240
    assert (np.asarray(display._reveal_frame(src, 1.0)).mean(axis=2) <= 2).mean() == 0.0


def test_every_frame_is_a_whole_panel():
    for t in (0.0, 0.25, 0.5, 0.75, 1.0):
        src = display._reveal_source(Image.new("RGB", (900, 400)))
        assert display._reveal_frame(src, t).size == (240, 240)


@pytest.fixture
def revealing(monkeypatch):
    """A wide picture mid-reveal, starting at t=1000 and showing for 15s."""
    src = display._reveal_source(Image.new("RGB", (1258, 635), (80, 90, 100)))
    monkeypatch.setattr(display, "_custom_reveal_src", src)
    monkeypatch.setattr(display, "_custom_reveal_t0", 1000.0)
    monkeypatch.setattr(display, "_custom_image_expiry", 1015.0)
    monkeypatch.setattr(display, "_custom_reveal_pan", (0.15, 0.5, 0.85, 0.5))
    return src


def test_the_first_phase_holds_the_whole_picture_still(revealing):
    scale, px, py, settled = display._reveal_view(1000.0)
    contain = 240 / max(revealing.size)
    assert scale == pytest.approx(contain) and settled is True
    assert display._reveal_view(1000.0 + display.REVEAL_HOLD_SECS - 0.01)[3] is True


def test_the_second_phase_eases_in_to_filling_the_panel(revealing):
    half = display._reveal_view(1000.0 + display.REVEAL_HOLD_SECS
                                + display.REVEAL_ZOOM_SECS / 2)
    contain = 240 / max(revealing.size)
    assert contain < half[0] < 1.0 and half[3] is False
    end = display._reveal_view(1000.0 + display.REVEAL_HOLD_SECS
                               + display.REVEAL_ZOOM_SECS - 0.01)
    assert end[0] > half[0]                 # still opening up


def test_the_third_phase_keeps_drifting_rather_than_stopping(revealing):
    t0 = 1000.0 + display.REVEAL_HOLD_SECS + display.REVEAL_ZOOM_SECS
    start = display._reveal_view(t0 + 0.01)
    late = display._reveal_view(t0 + 5.0)
    assert start[3] is False and late[3] is False       # never settles
    assert late[0] > start[0]                           # creeping further in
    assert late[1] > start[1]                           # and panning across
    assert 1.0 <= start[0] <= display.KEN_BURNS_ZOOM
    assert late[0] <= display.KEN_BURNS_ZOOM


def test_the_drift_is_bounded_by_the_end_of_the_showing(revealing):
    far = display._reveal_view(1000.0 + 600.0)
    assert far[0] == pytest.approx(display.KEN_BURNS_ZOOM)
    assert far[1] == pytest.approx(0.85)


def test_the_zoom_hands_over_to_the_drift_without_a_jump(revealing):
    t0 = 1000.0 + display.REVEAL_HOLD_SECS + display.REVEAL_ZOOM_SECS
    before = display._reveal_view(t0 - 0.001)
    after = display._reveal_view(t0 + 0.001)
    assert abs(after[0] - before[0]) < 0.01     # scale is continuous
    assert abs(after[1] - before[1]) < 0.01     # and so is the pan


def test_no_reveal_means_no_view(monkeypatch):
    monkeypatch.setattr(display, "_custom_reveal_src", None)
    assert display._reveal_view(1e9) is None


def test_asking_for_a_reveal_arms_one(monkeypatch):
    monkeypatch.setattr(display, "_available", True)
    monkeypatch.setattr(display, "_poke", lambda *a, **k: None)
    monkeypatch.setattr(display, "_custom_reveal_src", None)
    assert display.display_pil_image(Image.new("RGB", (900, 400)), reveal=True) is True
    assert display._custom_reveal_src is not None
    assert display._custom_image.size == (240, 240)


def test_text_screens_are_not_revealed(monkeypatch):
    # show_access_code and friends pass an image already built for the panel;
    # zooming into one would be absurd.
    monkeypatch.setattr(display, "_available", True)
    monkeypatch.setattr(display, "_poke", lambda *a, **k: None)
    monkeypatch.setattr(display, "_custom_reveal_src", Image.new("RGB", (480, 240)))
    display.display_pil_image(Image.new("RGB", (240, 240)))
    assert display._custom_reveal_src is None


def test_the_picture_arriving_ends_the_retrieval_animation(monkeypatch):
    """The animation outranks the custom image and has a three-second floor, which
    was swallowing the reveal's opening hold on the whole picture."""
    monkeypatch.setattr(display, "_available", True)
    monkeypatch.setattr(display, "_poke", lambda *a, **k: None)
    monkeypatch.setattr(display, "_retrieving_image", True)
    monkeypatch.setattr(display, "_image_retrieval_until", 1e18)
    assert display.display_pil_image(Image.new("RGB", (900, 400)), reveal=True) is True
    assert display._retrieving_image is False
    assert display._image_retrieval_until == 0.0


# ── panning across a filled panel ─────────────────────────────────────────────

def test_the_window_moves_when_the_pan_does():
    import numpy as np
    # A wide picture, dark on the left and bright on the right: panning right
    # must make the panel brighter.
    img = Image.new("RGB", (960, 240), (10, 10, 10))
    img.paste(Image.new("RGB", (480, 240), (240, 240, 240)), (480, 0))
    src = display._reveal_source(img)
    left = np.asarray(display._pan_zoom_frame(src, 1.0, px=0.0)).mean()
    right = np.asarray(display._pan_zoom_frame(src, 1.0, px=1.0)).mean()
    assert right > left + 100


def test_a_letterboxed_frame_ignores_the_pan():
    import numpy as np
    # Below fill scale there is no slack to pan into, so px must not shift it.
    src = display._reveal_source(Image.new("RGB", (960, 240), (120, 120, 120)))
    a = np.asarray(display._pan_zoom_frame(src, 0.25, px=0.0))
    b = np.asarray(display._pan_zoom_frame(src, 0.25, px=1.0))
    assert (a == b).all()


def test_the_pan_is_clamped_to_the_picture():
    # Nonsense values must not paste the window off the edge into black.
    import numpy as np
    src = display._reveal_source(Image.new("RGB", (960, 240), (120, 120, 120)))
    for px in (-5.0, 5.0):
        a = np.asarray(display._pan_zoom_frame(src, 1.2, px=px))
        assert (a.mean(axis=2) <= 2).mean() == 0.0      # no black edge showing


def test_every_pan_zoom_frame_is_a_whole_panel():
    src = display._reveal_source(Image.new("RGB", (900, 400)))
    for scale in (0.2, 0.6, 1.0, 1.18, 2.0):
        assert display._pan_zoom_frame(src, scale).size == (240, 240)


def test_a_wide_picture_drifts_sideways_and_a_tall_one_vertically():
    for _ in range(12):      # the direction is random; the axis is not
        px0, py0, px1, py1 = display._ken_burns_path((900, 400))
        assert py0 == py1 == 0.5 and px0 != px1
        px0, py0, px1, py1 = display._ken_burns_path((400, 900))
        assert px0 == px1 == 0.5 and py0 != py1


def test_a_square_picture_drifts_diagonally():
    px0, py0, px1, py1 = display._ken_burns_path((600, 600))
    assert px0 == py0 and px1 == py1 and px0 != px1


def test_the_drift_direction_varies_between_pictures():
    seen = {display._ken_burns_path((900, 400))[0] for _ in range(40)}
    assert len(seen) == 2       # it goes both ways, not always the same one
