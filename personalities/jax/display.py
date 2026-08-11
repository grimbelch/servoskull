import math
import time
from PIL import Image, ImageDraw

W = H = 240
_CX = _CY = 120

def _scale(rgb, k: float):
    k = max(0.0, min(1.0, k))
    return (int(rgb[0] * k), int(rgb[1] * k), int(rgb[2] * k))

def _heart_polygon(cx: float, cy: float, scale: float, num_points: int = 60) -> list[tuple[float, float]]:
    pts = []
    for i in range(num_points):
        t = 2.0 * math.pi * i / num_points
        x = 16.0 * (math.sin(t) ** 3)
        y = -(13.0 * math.cos(t) - 5.0 * math.cos(2.0 * t) - 2.0 * math.cos(3.0 * t) - math.cos(4.0 * t))
        pts.append((cx + x * scale, cy + y * scale + 3.5 * scale))
    return pts

def render_bezel() -> Image.Image:
    GOLD_RIM = (215, 170, 40)
    BRASS_EDGE = (140, 105, 25)
    DARK = (15, 12, 20)

    bg = Image.new("RGB", (W, H), (0, 0, 0))
    d = ImageDraw.Draw(bg)

    d.ellipse([_CX - 116, _CY - 116, _CX + 116, _CY + 116], fill=(35, 28, 20), outline=GOLD_RIM, width=5)
    d.ellipse([_CX - 110, _CY - 110, _CX + 110, _CY + 110], outline=BRASS_EDGE, width=2)

    for deg in range(0, 360, 45):
        a = math.radians(deg)
        sx, sy = _CX + 102 * math.cos(a), _CY + 102 * math.sin(a)
        d.ellipse([sx - 4, sy - 4, sx + 4, sy + 4], fill=GOLD_RIM, outline=(240, 200, 70))

    d.ellipse([_CX - 88, _CY - 88, _CX + 88, _CY + 88], fill=DARK, outline=(70, 50, 25), width=3)
    return bg

def render_frame(bezel: Image.Image, mask: Image.Image, amp: float, angle: float, blink: float, look_x: float, look_y: float, mood_rgb: tuple) -> Image.Image:
    img = bezel.rotate(angle, resample=Image.BICUBIC) if angle else bezel.copy()
    base = mood_rgb if mood_rgb != (255, 32, 32) else (240, 45, 80)
    now = time.monotonic()
    beat_cycle = (now * 2.2) % 1.0
    if beat_cycle < 0.15:
        rhythm_bounce = math.sin((beat_cycle / 0.15) * math.pi) * 0.22
    elif 0.25 < beat_cycle < 0.40:
        rhythm_bounce = math.sin(((beat_cycle - 0.25) / 0.15) * math.pi) * 0.14
    else:
        rhythm_bounce = 0.0

    base_scale = 3.2 + 2.8 * amp + rhythm_bounce * (1.0 + 0.5 * amp)
    intensity = 0.35 + 0.65 * amp

    cx = _CX + look_x
    cy = _CY + look_y

    layer = Image.new("RGB", (W, H), (0, 0, 0))
    d = ImageDraw.Draw(layer)

    d.polygon(_heart_polygon(cx, cy, scale=base_scale * 1.65), fill=_scale(base, intensity * 0.15))
    d.polygon(_heart_polygon(cx, cy, scale=base_scale * 1.35), fill=_scale(base, intensity * 0.40))
    d.polygon(_heart_polygon(cx, cy, scale=base_scale), fill=_scale(base, intensity), outline=_scale(base, min(1.0, intensity * 1.3)), width=2)
    d.polygon(_heart_polygon(cx, cy, scale=base_scale * 0.58), fill=_scale((255, 225, 235), min(1.0, intensity * 1.4)))

    hl_scale = max(1.5, base_scale * 0.25)
    hl_cx = cx - 3.8 * base_scale
    hl_cy = cy - 3.5 * base_scale
    d.ellipse([hl_cx - hl_scale, hl_cy - hl_scale, hl_cx + hl_scale, hl_cy + hl_scale], fill=(255, 255, 255))

    # Jax's beating heart display does not blink
    img.paste(layer, (0, 0), mask)
    return img

def render_overlay(bezel: Image.Image, mask: Image.Image, now: float, start_time: float, duration: float, mood_rgb: tuple) -> Image.Image:
    overlay = Image.new("RGB", (W, H), (0, 0, 0))
    d = ImageDraw.Draw(overlay)
    age = now - start_time
    
    def ease_in_out(t: float) -> float:
        t = max(0.0, min(1.0, t))
        return t * t * (3.0 - 2.0 * t)

    act1_end = 1.8
    paw_alpha = 1.0
    if age > act1_end:
        paw_fade_t = (age - act1_end) / 0.7
        paw_alpha = max(0.0, 1.0 - ease_in_out(paw_fade_t))

    if paw_alpha > 0.0:
        GOLD   = (int(235 * paw_alpha), int(175 * paw_alpha), int(50 * paw_alpha))
        GOLD_L = (int(255 * paw_alpha), int(210 * paw_alpha), int(90 * paw_alpha))
        main_t = ease_in_out(min(1.0, age / 0.6))
        main_r = main_t * 36
        if main_r > 0:
            d.ellipse([_CX - main_r, _CY + 10 - main_r, _CX + main_r, _CY + 10 + main_r], fill=GOLD, outline=GOLD_L, width=2)
        toe_positions = [(-32, -32), (-14, -45), (14, -45), (32, -32)]
        for idx, (ox, oy) in enumerate(toe_positions):
            toe_start = 0.5 + idx * 0.25
            toe_t = ease_in_out(min(1.0, max(0.0, (age - toe_start) / 0.3)))
            if toe_t > 0:
                tr = toe_t * 14
                d.ellipse([_CX + ox - tr, _CY + oy + 10 - tr, _CX + ox + tr, _CY + oy + 10 + tr], fill=GOLD, outline=GOLD_L, width=1)

    heart_alpha = 0.0
    if age > act1_end:
        heart_alpha = ease_in_out(min(1.0, (age - act1_end) / 1.0))

    if heart_alpha > 0.0:
        base_r = (240, 45, 80)
        base_p = (255, 225, 235)
        beat = (age * 2.2) % 1.0
        if beat < 0.15:
            pulse = math.sin((beat / 0.15) * math.pi) * 0.18
        elif 0.25 < beat < 0.40:
            pulse = math.sin(((beat - 0.25) / 0.15) * math.pi) * 0.10
        else:
            pulse = 0.0
        hscale = (3.8 + pulse) * heart_alpha
        
        hd_layer = Image.new("RGB", (W, H), (0, 0, 0))
        hd = ImageDraw.Draw(hd_layer)
        hd.polygon(_heart_polygon(_CX, _CY - 20, hscale * 1.65), fill=_scale(base_r, heart_alpha * 0.15))
        hd.polygon(_heart_polygon(_CX, _CY - 20, hscale * 1.35), fill=_scale(base_r, heart_alpha * 0.40))
        hd.polygon(_heart_polygon(_CX, _CY - 20, hscale), fill=_scale(base_r, heart_alpha))
        hd.polygon(_heart_polygon(_CX, _CY - 20, hscale * 0.58), fill=_scale(base_p, min(1.0, heart_alpha * 1.4)))
        
        d.bitmap((0, 0), hd_layer)
        # Using PIL paste would be better: 
        # Actually, since both are RGB and overlay is black where empty, we can't just overlay. 
        # We need an ImageChops.add.
        from PIL import ImageChops
        overlay = ImageChops.add(overlay, hd_layer)

    img = bezel.copy()
    img.paste(overlay, (0, 0), mask)
    return img

MOOD_COLOURS = {
    "VIGILANT": (240, 160, 40),
    "DUTIFUL": (240, 180, 50),
    "FERVENT": (255, 120, 20),
    "SUSPICIOUS": (200, 150, 40),
    "CONTEMPLATIVE": (60, 140, 255),
    "MELANCHOLIC": (90, 90, 200),
}
