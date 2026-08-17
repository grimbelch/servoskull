import math
import time
from PIL import Image, ImageDraw

W = H = 240
_CX = _CY = 120

def _scale(rgb, k: float):
    k = max(0.0, min(1.0, k))
    return (int(rgb[0] * k), int(rgb[1] * k), int(rgb[2] * k))

def _gear_polygon(n_teeth: int, r_root: float, r_tip: float,
                  tooth_frac: float = 0.52, tip_frac: float = 0.34,
                  gap_steps: int = 5):
    period = 2 * math.pi / n_teeth
    half_base = period * tooth_frac / 2
    half_tip = period * tip_frac / 2
    polar = []
    for i in range(n_teeth):
        a = i * period
        polar.append((a - half_base, r_root))
        polar.append((a - half_tip, r_tip))
        polar.append((a + half_tip, r_tip))
        polar.append((a + half_base, r_root))
        gap_start, gap_end = a + half_base, a + period - half_base
        for s in range(1, gap_steps):
            polar.append((gap_start + (gap_end - gap_start) * s / gap_steps, r_root))
    return [(_CX + r * math.cos(ang), _CY + r * math.sin(ang)) for ang, r in polar]

def render_bezel() -> Image.Image:
    GEAR = (60, 62, 70)
    EDGE = (120, 124, 138)
    DARK = (24, 25, 30)
    RIM = (150, 44, 24)

    bg = Image.new("RGB", (W, H), (0, 0, 0))
    d = ImageDraw.Draw(bg)

    d.polygon(_gear_polygon(11, r_root=96, r_tip=117), fill=GEAR, outline=EDGE, width=3)

    for deg in range(0, 360, 30):
        a = math.radians(deg)
        bx, by = _CX + 86 * math.cos(a), _CY + 86 * math.sin(a)
        d.ellipse([bx - 3, by - 3, bx + 3, by + 3], fill=DARK)

    d.ellipse([_CX - 80, _CY - 80, _CX + 80, _CY + 80], outline=EDGE, width=2)
    d.ellipse([_CX - 78, _CY - 78, _CX + 78, _CY + 78], fill=DARK)
    d.ellipse([_CX - 75, _CY - 75, _CX + 75, _CY + 75], outline=RIM, width=3)
    return bg

def render_frame(bezel: Image.Image, mask: Image.Image, amp: float, angle: float, blink: float, look_x: float, look_y: float, mood_rgb: tuple) -> Image.Image:
    img = bezel.rotate(angle, resample=Image.BICUBIC) if angle else bezel.copy()
    base = mood_rgb
    intensity = 0.25 + 0.75 * amp
    iris_r = 30 + 30 * amp

    cx = _CX + look_x
    cy = _CY + look_y

    iris = Image.new("RGB", (W, H), (0, 0, 0))
    d = ImageDraw.Draw(iris)

    def disc(r, colour):
        d.ellipse([cx - r, cy - r, cx + r, cy + r], fill=colour)

    disc(iris_r * 2.0, _scale(base, intensity * 0.12))
    disc(iris_r * 1.45, _scale(base, intensity * 0.32))
    disc(iris_r, _scale(base, intensity))
    disc(iris_r * 0.55, _scale(base, min(1.0, intensity * 1.4)))
    disc(iris_r * 0.26, (8, 0, 0))

    if blink > 0.0:
        open_h = max(1, int(round(H * (1.0 - blink))))
        squashed = iris.resize((W, open_h), resample=Image.BILINEAR)
        iris = Image.new("RGB", (W, H), (0, 0, 0))
        iris.paste(squashed, (0, (H - open_h) // 2))

    img.paste(iris, (0, 0), mask)
    return img

def render_overlay(bezel: Image.Image, mask: Image.Image, now: float, start_time: float, duration: float, mood_rgb: tuple) -> Image.Image:
    age = max(0.0, now - start_time)
    overlay = Image.new("RGB", (W, H), (0, 0, 0))
    d = ImageDraw.Draw(overlay)

    # ── Adeptus Mechanicus Skull-Cog (Scaled to Full-Screen 240x240) ──
    scale = min(1.0, age / 1.0)
    scale = scale * scale * (3.0 - 2.0 * scale)

    if scale > 0.01:
        gear_angle = (age * 90.0) % 360
        r_outer = 110.0 * scale
        r_inner = 85.0 * scale
        num_teeth = 12

        points = []
        for i in range(num_teeth):
            t_start = i * (360.0 / num_teeth)
            cycle_deg = 360.0 / num_teeth
            a1 = gear_angle + t_start
            a2 = gear_angle + t_start + cycle_deg * 0.4
            a3 = gear_angle + t_start + cycle_deg * 0.5
            a4 = gear_angle + t_start + cycle_deg * 0.9

            points.append((_CX + r_outer * math.cos(math.radians(a1)), _CY + r_outer * math.sin(math.radians(a1))))
            points.append((_CX + r_outer * math.cos(math.radians(a2)), _CY + r_outer * math.sin(math.radians(a2))))
            points.append((_CX + r_inner * math.cos(math.radians(a3)), _CY + r_inner * math.sin(math.radians(a3))))
            points.append((_CX + r_inner * math.cos(math.radians(a4)), _CY + r_inner * math.sin(math.radians(a4))))

        d.polygon(points, fill=(235, 230, 215))

        r_center = 68.0 * scale
        d.ellipse([_CX - r_center, _CY - r_center, _CX + r_center, _CY + r_center], fill=(0, 0, 0))

        # Left cranium (bone)
        d.pieslice([_CX - 27 * scale, _CY - 34 * scale, _CX + 27 * scale, _CY + 20 * scale], 90, 270, fill=(235, 230, 215))
        # Right cranium (machine)
        d.pieslice([_CX - 27 * scale, _CY - 34 * scale, _CX + 27 * scale, _CY + 20 * scale], 270, 90, fill=(80, 85, 95))

        # Left jaw
        d.polygon([
            (_CX - 15 * scale, _CY + 20 * scale),
            (_CX, _CY + 20 * scale),
            (_CX, _CY + 37 * scale),
            (_CX - 12 * scale, _CY + 37 * scale)
        ], fill=(235, 230, 215))
        # Right jaw
        d.polygon([
            (_CX, _CY + 20 * scale),
            (_CX + 15 * scale, _CY + 20 * scale),
            (_CX + 12 * scale, _CY + 37 * scale),
            (_CX, _CY + 37 * scale)
        ], fill=(80, 85, 95))

        # Cheekbones
        d.ellipse([_CX - 31 * scale, _CY - 3 * scale, _CX - 17 * scale, _CY + 10 * scale], fill=(235, 230, 215))
        d.ellipse([_CX + 17 * scale, _CY - 3 * scale, _CX + 31 * scale, _CY + 10 * scale], fill=(80, 85, 95))

        # Left eye
        d.ellipse([_CX - 15 * scale, _CY - 7 * scale, _CX - 5 * scale, _CY + 3 * scale], fill=(0, 0, 0))
        # Right eye (glowing green/mood)
        d.ellipse([_CX + 5 * scale, _CY - 7 * scale, _CX + 15 * scale, _CY + 3 * scale], fill=mood_rgb)

        # Nose
        d.polygon([
            (_CX - 3 * scale, _CY + 14 * scale),
            (_CX, _CY + 7 * scale),
            (_CX + 3 * scale, _CY + 14 * scale)
        ], fill=(0, 0, 0))

        # Teeth slits
        for offset in (-8, -3):
            d.line([(_CX + offset * scale, _CY + 20 * scale), (_CX + offset * scale, _CY + 34 * scale)], fill=(0, 0, 0), width=1)
        for offset in (3, 8):
            d.line([(_CX + offset * scale, _CY + 20 * scale), (_CX + offset * scale, _CY + 34 * scale)], fill=(0, 0, 0), width=1)
        d.line([(_CX, _CY + 20 * scale), (_CX, _CY + 37 * scale)], fill=(0, 0, 0), width=1)

    return overlay

MOOD_COLOURS = {
    "VIGILANT": (255, 40, 30),
    "DUTIFUL": (255, 70, 25),
    "FERVENT": (255, 120, 20),
    "SUSPICIOUS": (255, 200, 30),
    "CONTEMPLATIVE": (60, 140, 255),
    "MELANCHOLIC": (90, 90, 200),
}
