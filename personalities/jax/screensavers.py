"""jax/screensavers.py - Dog-themed idle animations for Jax."""

import math
import random
import time
from PIL import Image, ImageDraw, ImageFont

SCREENSAVER_ANIMS = [
    "bouncing_ball",
    "dog_bone",
    "paw_prints",
    "sniffing_nose",
    "digging",
    "chasing_squirrel",
    "fire_hydrant",
    "dog_tag",
    "bark_ripples",
    "collar_rings",
    "dog_house",
    "rolling_grass",
    "dog_bowl",
    "heartbeat",
    "panting_tongue"
]

def get_screensaver_names() -> list[str]:
    return list(SCREENSAVER_ANIMS)

# State variables
_bouncing_ball_x = 120.0
_bouncing_ball_y = 120.0
_bouncing_ball_dx = 2.5
_bouncing_ball_dy = 1.2

_tail_angle = 0.0
_bone_angle = 0.0

_paw_prints = []

_frisbee_x = -20.0
_frisbee_y = 120.0
_frisbee_dx = 3.0
_frisbee_dy = 0.0

_sleep_particles = []
_dirt_particles = []
_squirrel_angle = 0.0
_hydrant_x = 240.0
_tag_angle = 0.0
_treats = []
_bark_ripples = []
_collar_rings = []
_grass_blades = []
_water_droplets = []
_heartbeat_x = 0.0
_heartbeat_history = []
_panting_phase = 0.0
_fetch_stick_x = 240.0
_fetch_stick_y = 120.0

def _init_paw_prints():
    global _paw_prints
    _paw_prints = []
    for _ in range(5):
        _paw_prints.append({
            "x": random.uniform(40, 200),
            "y": random.uniform(40, 200),
            "alpha": random.uniform(0, 255),
            "fade_dir": random.choice([-2.0, 2.0])
        })

def _init_sleep_particles():
    global _sleep_particles
    _sleep_particles = []
    for _ in range(5):
        _sleep_particles.append({
            "x": random.uniform(100, 140),
            "y": random.uniform(120, 160),
            "speed": random.uniform(0.5, 1.5),
            "alpha": random.uniform(0, 255)
        })

def _init_dirt():
    global _dirt_particles
    _dirt_particles = []
    for _ in range(20):
        _dirt_particles.append({
            "x": random.uniform(90, 150),
            "y": 200,
            "dx": random.uniform(-3, 3),
            "dy": random.uniform(-6, -2)
        })

def _init_treats():
    global _treats
    _treats = []
    for _ in range(10):
        _treats.append({
            "x": random.uniform(20, 220),
            "y": random.uniform(-100, 240),
            "speed": random.uniform(2, 5),
            "rot": random.uniform(0, 360)
        })

def _init_grass():
    global _grass_blades
    _grass_blades = []
    for x in range(10, 230, 8):
        _grass_blades.append({
            "x": x,
            "height": random.uniform(20, 50),
            "phase": random.uniform(0, 6.28)
        })

def _render_bouncing_ball_frame(bezel, mask, now):
    global _bouncing_ball_x, _bouncing_ball_y, _bouncing_ball_dx, _bouncing_ball_dy
    _bouncing_ball_x += _bouncing_ball_dx
    _bouncing_ball_y += _bouncing_ball_dy
    if _bouncing_ball_x < 20 or _bouncing_ball_x > 220: _bouncing_ball_dx *= -1
    if _bouncing_ball_y < 20 or _bouncing_ball_y > 220: _bouncing_ball_dy *= -1
    
    img = Image.new("RGB", (240, 240), (0, 0, 0))
    d = ImageDraw.Draw(img)
    d.ellipse([_bouncing_ball_x-15, _bouncing_ball_y-15, _bouncing_ball_x+15, _bouncing_ball_y+15], fill=(150, 255, 0))
    # Tennis ball curves
    d.arc([_bouncing_ball_x-20, _bouncing_ball_y-15, _bouncing_ball_x, _bouncing_ball_y+15], 270, 90, fill=(255,255,255), width=2)
    d.arc([_bouncing_ball_x, _bouncing_ball_y-15, _bouncing_ball_x+20, _bouncing_ball_y+15], 90, 270, fill=(255,255,255), width=2)
    return img

def _render_wagging_tail_frame(bezel, mask, now):
    img = Image.new("RGB", (240, 240), (0, 0, 0))
    d = ImageDraw.Draw(img)
    angle = math.sin(now * 10) * 0.8
    # Pivot at bottom center
    px, py = 120, 200
    length = 80
    end_x = px + math.sin(angle) * length
    end_y = py - math.cos(angle) * length
    d.line([(px, py), (end_x, end_y)], fill=(200, 150, 50), width=20)
    d.ellipse([end_x-10, end_y-10, end_x+10, end_y+10], fill=(255, 255, 255))
    return img

def _render_dog_bone_frame(bezel, mask, now):
    img = Image.new("RGB", (240, 240), (0, 0, 0))
    d = ImageDraw.Draw(img)
    cx, cy = 120, 120
    angle = now * 2.0
    w, h = 60, 20
    cos_a = math.cos(angle)
    sin_a = math.sin(angle)
    # Draw a rotated rectangle and 4 circles for the bone
    pts = [
        (-w, -h), (w, -h), (w, h), (-w, h)
    ]
    rot_pts = []
    for x, y in pts:
        rx = cx + x * cos_a - y * sin_a
        ry = cy + x * sin_a + y * cos_a
        rot_pts.append((rx, ry))
    d.polygon(rot_pts, fill=(220, 220, 200))
    
    # Bone ends
    for ex, ey in [(-w, -h*1.2), (-w, h*1.2), (w, -h*1.2), (w, h*1.2)]:
        rx = cx + ex * cos_a - ey * sin_a
        ry = cy + ex * sin_a + ey * cos_a
        d.ellipse([rx-15, ry-15, rx+15, ry+15], fill=(220, 220, 200))
    return img

def _render_paw_prints_frame(bezel, mask, now):
    global _paw_prints
    if not _paw_prints:
        _init_paw_prints()
    img = Image.new("RGB", (240, 240), (0, 0, 0))
    d = ImageDraw.Draw(img)
    for p in _paw_prints:
        p["alpha"] += p["fade_dir"]
        if p["alpha"] > 255:
            p["alpha"] = 255
            p["fade_dir"] = -2.0
        elif p["alpha"] < 0:
            p["alpha"] = 0
            p["x"] = random.uniform(40, 200)
            p["y"] = random.uniform(40, 200)
            p["fade_dir"] = 2.0
        
        a = int(p["alpha"])
        c = (a, a//2, a//4)
        x, y = p["x"], p["y"]
        # main pad
        d.ellipse([x-15, y, x+15, y+20], fill=c)
        # toes
        d.ellipse([x-25, y-15, x-10, y], fill=c)
        d.ellipse([x-10, y-25, x+5, y-10], fill=c)
        d.ellipse([x+5, y-25, x+20, y-10], fill=c)
        d.ellipse([x+15, y-15, x+30, y], fill=c)
    return img

def _render_sniffing_nose_frame(bezel, mask, now):
    img = Image.new("RGB", (240, 240), (0, 0, 0))
    d = ImageDraw.Draw(img)
    scale = 1.0 + 0.1 * math.sin(now * 5.0)
    w, h = 80 * scale, 50 * scale
    cx, cy = 120, 120
    # Nose
    d.ellipse([cx-w, cy-h, cx+w, cy+h], fill=(30, 30, 30))
    # Nostrils
    nw, nh = 15 * scale, 25 * scale
    d.ellipse([cx-w*0.5-nw, cy-nh, cx-w*0.5+nw, cy+nh], fill=(0, 0, 0))
    d.ellipse([cx+w*0.5-nw, cy-nh, cx+w*0.5+nw, cy+nh], fill=(0, 0, 0))
    # Shine
    d.ellipse([cx-20, cy-h+10, cx+20, cy-h+25], fill=(100, 100, 100))
    return img

def _render_catch_frisbee_frame(bezel, mask, now):
    global _frisbee_x, _frisbee_y
    _frisbee_x += 4.0
    _frisbee_y = 120 + 40 * math.sin(_frisbee_x * 0.05)
    if _frisbee_x > 260:
        _frisbee_x = -40
    
    img = Image.new("RGB", (240, 240), (0, 0, 0))
    d = ImageDraw.Draw(img)
    # Dog silhouette on right
    d.ellipse([180, 100, 240, 200], fill=(100, 70, 30))
    d.polygon([(180, 100), (200, 60), (220, 100)], fill=(100, 70, 30))
    
    # Frisbee
    d.ellipse([_frisbee_x-20, _frisbee_y-5, _frisbee_x+20, _frisbee_y+5], fill=(255, 0, 0))
    return img

def _render_sleeping_dog_frame(bezel, mask, now):
    global _sleep_particles
    if not _sleep_particles:
        _init_sleep_particles()
    img = Image.new("RGB", (240, 240), (0, 0, 0))
    d = ImageDraw.Draw(img)
    
    # Dog sleeping
    breath = 5 * math.sin(now * 2.0)
    d.ellipse([60, 160-breath, 180, 220], fill=(150, 100, 50))
    d.ellipse([140, 180, 200, 230], fill=(120, 80, 40)) # Head
    
    try:
        font = ImageFont.load_default()
    except:
        font = None
        
    for p in _sleep_particles:
        p["y"] -= p["speed"]
        p["x"] += math.sin(now * 3 + p["y"])
        if p["y"] < 20:
            p["y"] = random.uniform(120, 160)
            p["x"] = random.uniform(140, 180)
        a = int(p["alpha"] * (p["y"] / 160))
        c = (a, a, a)
        if font:
            d.text((p["x"], p["y"]), "Z", fill=c, font=font)
        else:
            d.ellipse([p["x"], p["y"], p["x"]+10, p["y"]+10], fill=c)
    return img

def _render_digging_frame(bezel, mask, now):
    global _dirt_particles
    if not _dirt_particles:
        _init_dirt()
    img = Image.new("RGB", (240, 240), (0, 0, 0))
    d = ImageDraw.Draw(img)
    # Dog rear end
    d.ellipse([80, 140, 160, 240], fill=(180, 120, 50))
    d.polygon([(110, 140), (120, 80), (130, 140)], fill=(180, 120, 50)) # Tail
    
    for p in _dirt_particles:
        p["x"] += p["dx"]
        p["y"] += p["dy"]
        p["dy"] += 0.5 # gravity
        if p["y"] > 240:
            p["y"] = 200
            p["x"] = random.uniform(90, 150)
            p["dx"] = random.uniform(-4, 4)
            p["dy"] = random.uniform(-8, -3)
        d.ellipse([p["x"]-2, p["y"]-2, p["x"]+2, p["y"]+2], fill=(100, 60, 20))
    return img

def _render_chasing_squirrel_frame(bezel, mask, now):
    global _squirrel_angle
    _squirrel_angle += 0.05
    img = Image.new("RGB", (240, 240), (0, 0, 0))
    d = ImageDraw.Draw(img)
    
    # Squirrel
    sx = 120 + 80 * math.cos(_squirrel_angle)
    sy = 120 + 80 * math.sin(_squirrel_angle)
    d.ellipse([sx-8, sy-8, sx+8, sy+8], fill=(150, 150, 150))
    
    # Dog
    dx = 120 + 80 * math.cos(_squirrel_angle - 0.5)
    dy = 120 + 80 * math.sin(_squirrel_angle - 0.5)
    d.ellipse([dx-15, dy-15, dx+15, dy+15], fill=(200, 140, 40))
    
    return img

def _render_fire_hydrant_frame(bezel, mask, now):
    global _hydrant_x
    _hydrant_x -= 2.0
    if _hydrant_x < -50:
        _hydrant_x = 290
    img = Image.new("RGB", (240, 240), (0, 0, 0))
    d = ImageDraw.Draw(img)
    hx, hy = _hydrant_x, 120
    d.rectangle([hx-15, hy, hx+15, hy+80], fill=(200, 0, 0))
    d.ellipse([hx-20, hy-10, hx+20, hy+10], fill=(200, 0, 0))
    d.rectangle([hx-25, hy+30, hx+25, hy+40], fill=(150, 0, 0))
    return img

def _render_dog_tag_frame(bezel, mask, now):
    img = Image.new("RGB", (240, 240), (0, 0, 0))
    d = ImageDraw.Draw(img)
    angle = math.sin(now * 3) * 0.5
    cx, cy = 120, 20
    length = 100
    tx = cx + length * math.sin(angle)
    ty = cy + length * math.cos(angle)
    
    d.line([(cx, cy), (tx, ty)], fill=(200, 200, 200), width=3)
    
    try:
        font = ImageFont.load_default()
    except:
        font = None
        
    d.ellipse([tx-30, ty-30, tx+30, ty+30], fill=(255, 215, 0))
    if font:
        d.text((tx-12, ty-5), "JAX", fill=(0, 0, 0), font=font)
    return img

def _render_treat_rain_frame(bezel, mask, now):
    global _treats
    if not _treats:
        _init_treats()
    img = Image.new("RGB", (240, 240), (0, 0, 0))
    d = ImageDraw.Draw(img)
    
    for t in _treats:
        t["y"] += t["speed"]
        t["rot"] += 5
        if t["y"] > 250:
            t["y"] = -30
            t["x"] = random.uniform(20, 220)
        
        # draw treat (bone shape)
        rx = t["x"]
        ry = t["y"]
        d.ellipse([rx-10, ry-5, rx+10, ry+5], fill=(180, 120, 50))
    return img

def _render_bark_ripples_frame(bezel, mask, now):
    global _bark_ripples
    img = Image.new("RGB", (240, 240), (0, 0, 0))
    d = ImageDraw.Draw(img)
    
    if random.random() < 0.05:
        _bark_ripples.append({"r": 10, "alpha": 255})
        
    for r in _bark_ripples:
        r["r"] += 3.0
        r["alpha"] -= 5
        a = max(0, int(r["alpha"]))
        d.ellipse([120-r["r"], 120-r["r"], 120+r["r"], 120+r["r"]], outline=(a, a, a), width=2)
        
    _bark_ripples = [r for r in _bark_ripples if r["alpha"] > 0]
    return img

def _render_collar_rings_frame(bezel, mask, now):
    img = Image.new("RGB", (240, 240), (0, 0, 0))
    d = ImageDraw.Draw(img)
    
    for i, color in enumerate([(255,0,0), (0,255,0), (0,0,255)]):
        a = now * (1.0 + i * 0.5)
        r = 50 + i * 20
        d.ellipse([120-r, 120-r, 120+r, 120+r], outline=color, width=4)
        x = 120 + r * math.cos(a)
        y = 120 + r * math.sin(a)
        d.ellipse([x-10, y-10, x+10, y+10], fill=(255, 255, 255))
    return img

def _render_dog_house_frame(bezel, mask, now):
    img = Image.new("RGB", (240, 240), (0, 0, 0))
    d = ImageDraw.Draw(img)
    
    # House body
    d.rectangle([60, 100, 180, 220], fill=(150, 50, 50))
    # Roof
    d.polygon([(40, 100), (120, 40), (200, 100)], fill=(80, 40, 40))
    # Door
    d.ellipse([90, 120, 150, 180], fill=(0, 0, 0))
    d.rectangle([90, 150, 150, 220], fill=(0, 0, 0))
    
    # Eyes blinking inside
    if math.sin(now * 4) > -0.8:
        d.ellipse([105, 150, 115, 160], fill=(255, 255, 0))
        d.ellipse([125, 150, 135, 160], fill=(255, 255, 0))
        
    return img

def _render_rolling_grass_frame(bezel, mask, now):
    global _grass_blades
    if not _grass_blades:
        _init_grass()
    img = Image.new("RGB", (240, 240), (0, 0, 0))
    d = ImageDraw.Draw(img)
    
    for b in _grass_blades:
        wind = math.sin(now * 2.0 + b["phase"]) * 20
        d.line([(b["x"], 240), (b["x"] + wind, 240 - b["height"])], fill=(0, 200, 50), width=4)
    return img

def _render_dog_bowl_frame(bezel, mask, now):
    img = Image.new("RGB", (240, 240), (0, 0, 0))
    d = ImageDraw.Draw(img)
    
    # Bowl
    d.ellipse([60, 160, 180, 200], fill=(100, 100, 100))
    d.rectangle([70, 180, 170, 220], fill=(100, 100, 100))
    
    # Water ripples
    r = (now * 20) % 40
    d.ellipse([120-r, 180-r*0.3, 120+r, 180+r*0.3], outline=(100, 200, 255), width=2)
    return img

def _render_heartbeat_frame(bezel, mask, now):
    global _heartbeat_x, _heartbeat_history
    _heartbeat_x = (_heartbeat_x + 4) % 240
    y = 120
    if 100 < _heartbeat_x < 110:
        y -= 40
    elif 110 <= _heartbeat_x < 130:
        y += 50
    elif 130 <= _heartbeat_x < 140:
        y -= 20
        
    _heartbeat_history.append((_heartbeat_x, y))
    if len(_heartbeat_history) > 60:
        _heartbeat_history.pop(0)
        
    img = Image.new("RGB", (240, 240), (0, 0, 0))
    d = ImageDraw.Draw(img)
    for i in range(1, len(_heartbeat_history)):
        d.line([_heartbeat_history[i-1], _heartbeat_history[i]], fill=(255, 50, 50), width=3)
    return img

def _render_panting_tongue_frame(bezel, mask, now):
    img = Image.new("RGB", (240, 240), (0, 0, 0))
    d = ImageDraw.Draw(img)
    
    pant = math.sin(now * 8) * 10
    
    # Nose
    d.ellipse([90, 80, 150, 120], fill=(30, 30, 30))
    # Mouth line
    d.line([(80, 140), (120, 160), (160, 140)], fill=(200, 200, 200), width=4)
    # Tongue
    d.ellipse([100, 150, 140, 200 + pant], fill=(255, 100, 100))
    return img

def _render_fetch_frame(bezel, mask, now):
    global _fetch_stick_x, _fetch_stick_y
    _fetch_stick_x -= 3
    if _fetch_stick_x < -50:
        _fetch_stick_x = 290
        _fetch_stick_y = random.uniform(80, 160)
        
    img = Image.new("RGB", (240, 240), (0, 0, 0))
    d = ImageDraw.Draw(img)
    
    # Stick
    sx, sy = _fetch_stick_x, _fetch_stick_y
    d.line([(sx-20, sy-10), (sx+20, sy+10)], fill=(139, 69, 19), width=8)
    
    # Dog chasing
    d.ellipse([sx+40, sy-20, sx+100, sy+20], fill=(200, 140, 40))
    return img

def render_screensaver_frame(anim_name: str, bezel, mask, now: float) -> Image.Image:
    render_fn_name = f"_render_{anim_name}_frame"
    if anim_name in SCREENSAVER_ANIMS:
        try:
            return globals()[render_fn_name](bezel, mask, now)
        except Exception as e:
            print(f"Error rendering {anim_name}: {e}")
    # Fallback to black image
    return Image.new("RGB", (240, 240), (0, 0, 0))
