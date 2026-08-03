"""skull/screensavers.py – Cogitator Visual Emulation (Screensaver Animations).

Contains all Adeptus Mechanicus themed screensavers for the GC9A01 circular HUD,
including vector arcade emulation (Asteroids), plasma, lissajous, canticle rain,
starfield, warp core, voronoi, data stream, mandala, rune wheel, etc.
"""

import math
import random
import time
import numpy as np
from PIL import Image, ImageDraw, ImageFont

# Master list of all available screensaver animations
SCREENSAVER_ANIMS = [
    "pong", "canticle_rain", "starfield", "oscilloscope", "game_of_life", "radar",
    "warp_core", "circuit_maze", "double_helix", "spinning_rings", "wireframe_cube",
    "bouncing_cog", "fractal_tree", "hud_status", "orbitals", "spectrum_bars",
    "plasma", "lissajous", "voronoi", "data_stream", "mandala",
    "rune_wheel", "glitch", "dna_helix", "neural_net", "gravity_well",
    "void_shield", "hex_grid", "kaleidoscope", "particle_burst", "asteroids"
]


def get_screensaver_names() -> list[str]:
    """Return authoritative list of screensaver animation names."""
    return list(SCREENSAVER_ANIMS)


# ── Global State Variables for Screensavers ───────────────────────────────────

# Pong
_pong_ball_x = 120.0
_pong_ball_y = 120.0
_pong_ball_dx = 2.5
_pong_ball_dy = 1.2
_pong_paddle_l_y = 120.0
_pong_paddle_r_y = 120.0
_pong_score_l = 0
_pong_score_r = 0

# Canticle Rain
_rain_cols = []

# Starfield
_starfield_stars = []

# Game of Life
_gol_grid = None
_gol_last_grids = []

# Radar
_radar_blips = []

# Circuit Maze
_maze_grid = []
_maze_last_flip = 0.0

# Bouncing Cog
_bc_x = 120.0
_bc_y = 120.0
_bc_dx = 1.8
_bc_dy = 1.3
_bc_angle = 0.0

# Orbitals
_orbital_particles = []

# Spectrum Bars
_spectrum_heights = [0.0] * 8
_spectrum_targets = [0.0] * 8
_spectrum_last_update = 0.0

# Voronoi
_voronoi_sites = []
_voronoi_last_shift = 0.0

# Data Stream
_data_stream_lines = []

# Neural Net
_neural_nodes = []
_neural_edges = []
_neural_pulses = []

# Morse Code
_morse_message = ""
_morse_pos = 0
_morse_last_advance = 0.0

# Hex Grid
_hex_grid_cells = []
_hex_last_flash = 0.0

# Particle Burst
_pburst_particles = []

# Asteroids Arcade State
_ast_ship = None
_ast_asteroids = []
_ast_bullets = []
_ast_sparks = []
_ast_score = 0
_ast_last_shot = 0.0


# ── Initializers ─────────────────────────────────────────────────────────────

def _init_canticle_rain():
    global _rain_cols
    _rain_cols = []
    for x in range(8, 233, 12):
        _rain_cols.append({
            "x": x,
            "y": random.uniform(-100, 240),
            "speed": random.uniform(2.0, 5.0),
            "chars": [random.choice(["0", "1"]) for _ in range(12)]
        })


def _init_starfield():
    global _starfield_stars
    _starfield_stars = []
    for _ in range(60):
        _starfield_stars.append({
            "x": random.uniform(-120, 120),
            "y": random.uniform(-120, 120),
            "z": random.uniform(1.0, 120.0),
            "speed": random.uniform(1.5, 3.5)
        })


def _init_game_of_life():
    global _gol_grid, _gol_last_grids
    _gol_grid = [[random.choice([0, 1]) for _ in range(24)] for _ in range(24)]
    _gol_last_grids = []


def _init_radar():
    global _radar_blips
    _radar_blips = []
    for _ in range(4):
        dist = random.uniform(30, 105)
        angle = random.uniform(0, math.pi * 2)
        _radar_blips.append({
            "x": 120.0 + dist * math.cos(angle),
            "y": 120.0 + dist * math.sin(angle),
            "brightness": 0.0,
            "angle": angle
        })


def _init_circuit_maze():
    global _maze_grid, _maze_last_flip
    _maze_grid = [[random.choice([0, 1]) for _ in range(24)] for _ in range(24)]
    _maze_last_flip = 0.0


def _init_bouncing_cog():
    global _bc_x, _bc_y, _bc_dx, _bc_dy, _bc_angle
    _bc_x = 120.0
    _bc_y = 120.0
    _bc_dx = random.choice([-1.8, 1.8])
    _bc_dy = random.uniform(-1.5, 1.5)
    _bc_angle = 0.0


def _init_orbitals():
    global _orbital_particles
    _orbital_particles = []
    for i in range(3):
        _orbital_particles.append({
            "speed": random.uniform(1.5, 3.5),
            "radius_x": random.uniform(20, 45),
            "radius_y": random.uniform(10, 25),
            "rot": random.uniform(0, math.pi * 2)
        })


def _init_spectrum_bars():
    global _spectrum_heights, _spectrum_targets, _spectrum_last_update
    _spectrum_heights = [random.uniform(5, 160) for _ in range(12)]
    _spectrum_targets = [random.uniform(5, 160) for _ in range(12)]
    _spectrum_last_update = 0.0


def _init_voronoi():
    global _voronoi_sites, _voronoi_last_shift
    palette_options = [
        (0, random.randint(140, 220), random.randint(30, 80)),
        (0, random.randint(80, 150), random.randint(20, 50)),
        (random.randint(120, 180), random.randint(60, 100), 0),
        (0, random.randint(100, 160), random.randint(100, 160)),
    ]
    _voronoi_sites = [{"x": random.uniform(20, 220), "y": random.uniform(20, 220),
                       "dx": random.uniform(-0.8, 0.8), "dy": random.uniform(-0.8, 0.8),
                       "c": random.choice(palette_options)}
                      for _ in range(7)]
    _voronoi_last_shift = 0.0


def _init_data_stream():
    global _data_stream_lines
    _data_stream_lines = [{"y": random.uniform(0, 240), "speed": random.uniform(1.5, 4.5),
                           "text": "".join(random.choices("0123456789ABCDEF", k=20))} for _ in range(14)]


def _init_neural_net():
    global _neural_nodes, _neural_edges, _neural_pulses
    _neural_nodes = [{"x": random.uniform(30, 210), "y": random.uniform(30, 210)} for _ in range(16)]
    _neural_edges = []
    for i in range(len(_neural_nodes)):
        for j in range(i + 1, len(_neural_nodes)):
            dx = _neural_nodes[i]["x"] - _neural_nodes[j]["x"]
            dy = _neural_nodes[i]["y"] - _neural_nodes[j]["y"]
            if math.sqrt(dx*dx + dy*dy) < 80:
                _neural_edges.append((i, j))
    _neural_pulses = []


def _init_hex_grid():
    global _hex_grid_cells
    _hex_grid_cells = []
    size = 14
    for row in range(11):
        for col in range(9):
            x = col * size * 1.73 + (row % 2) * size * 0.87 + 5
            y = row * size * 1.5 + 5
            _hex_grid_cells.append({"x": x, "y": y, "flash": 0.0, "size": size})


def _init_particle_burst():
    global _pburst_particles
    _pburst_particles = []


def _create_asteroid_polygon(radius):
    """Generate irregular vector polygon vertices for an asteroid."""
    pts = []
    num_verts = random.randint(7, 11)
    for i in range(num_verts):
        angle = i * (2 * math.pi / num_verts)
        r = radius * random.uniform(0.75, 1.25)
        pts.append((r * math.cos(angle), r * math.sin(angle)))
    return pts


def _init_asteroids():
    global _ast_ship, _ast_asteroids, _ast_bullets, _ast_sparks, _ast_score, _ast_last_shot
    _ast_ship = {
        "x": 120.0, "y": 120.0, "vx": 0.0, "vy": 0.0,
        "angle": -math.pi / 2, "thrusting": False
    }
    _ast_asteroids = []
    for _ in range(5):
        rad = random.uniform(16, 24)
        _ast_asteroids.append({
            "x": random.uniform(20, 220),
            "y": random.uniform(20, 220),
            "vx": random.uniform(-1.2, 1.2),
            "vy": random.uniform(-1.2, 1.2),
            "radius": rad,
            "rot": random.uniform(0, math.pi * 2),
            "rot_spd": random.uniform(-0.04, 0.04),
            "poly": _create_asteroid_polygon(rad)
        })
    _ast_bullets = []
    _ast_sparks = []
    _ast_score = 0
    _ast_last_shot = 0.0


# ── Renderers ────────────────────────────────────────────────────────────────

def _render_pong_frame(bezel, mask, now):
    global _pong_ball_x, _pong_ball_y, _pong_ball_dx, _pong_ball_dy
    global _pong_paddle_l_y, _pong_paddle_r_y, _pong_score_l, _pong_score_r
    min_x, max_x = 10, 230
    min_y, max_y = 10, 230
    
    _pong_ball_x += _pong_ball_dx
    _pong_ball_y += _pong_ball_dy
    
    if _pong_ball_y <= min_y + 3:
        _pong_ball_y = min_y + 3
        _pong_ball_dy = -_pong_ball_dy
    elif _pong_ball_y >= max_y - 3:
        _pong_ball_y = max_y - 3
        _pong_ball_dy = -_pong_ball_dy
        
    l_target = _pong_ball_y
    _pong_paddle_l_y += (l_target - _pong_paddle_l_y) * 0.12
    _pong_paddle_l_y = max(min_y + 15, min(max_y - 15, _pong_paddle_l_y))
    
    r_target = _pong_ball_y
    _pong_paddle_r_y += (r_target - _pong_paddle_r_y) * 0.12
    _pong_paddle_r_y = max(min_y + 15, min(max_y - 15, _pong_paddle_r_y))
    
    if _pong_ball_dx < 0 and _pong_ball_x <= min_x + 8:
        if abs(_pong_ball_y - _pong_paddle_l_y) <= 18:
            _pong_ball_x = min_x + 8
            _pong_ball_dx = -_pong_ball_dx
            _pong_ball_dy += (_pong_ball_y - _pong_paddle_l_y) * 0.15
        else:
            _pong_score_r += 1
            _pong_ball_x, _pong_ball_y = 120.0, 120.0
            _pong_ball_dx = 2.0
            _pong_ball_dy = random.uniform(-1.0, 1.0)
    elif _pong_ball_dx > 0 and _pong_ball_x >= max_x - 8:
        if abs(_pong_ball_y - _pong_paddle_r_y) <= 18:
            _pong_ball_x = max_x - 8
            _pong_ball_dx = -_pong_ball_dx
            _pong_ball_dy += (_pong_ball_y - _pong_paddle_r_y) * 0.15
        else:
            _pong_score_l += 1
            _pong_ball_x, _pong_ball_y = 120.0, 120.0
            _pong_ball_dx = -2.0
            _pong_ball_dy = random.uniform(-1.0, 1.0)
            
    img = Image.new("RGB", (240, 240), (0, 10, 5))
    d = ImageDraw.Draw(img)
    
    for y in range(min_y, max_y, 10):
        d.line([(120, y), (120, y + 5)], fill=(0, 100, 40), width=1)
        
    try:
        font = ImageFont.load_default()
    except Exception:
        font = None
    if font:
        d.text((95, 20), str(_pong_score_l), fill=(0, 200, 70), font=font)
        d.text((135, 20), str(_pong_score_r), fill=(0, 200, 70), font=font)
        
    d.rectangle([min_x, _pong_paddle_l_y - 15, min_x + 3, _pong_paddle_l_y + 15], fill=(0, 220, 80))
    d.rectangle([max_x - 3, _pong_paddle_r_y - 15, max_x, _pong_paddle_r_y + 15], fill=(0, 220, 80))
    d.ellipse([_pong_ball_x - 3, _pong_ball_y - 3, _pong_ball_x + 3, _pong_ball_y + 3], fill=(0, 255, 100))
    return img


def _render_canticle_rain_frame(bezel, mask, now):
    global _rain_cols
    if not _rain_cols:
        _init_canticle_rain()
        
    img = Image.new("RGB", (240, 240), (0, 8, 3))
    d = ImageDraw.Draw(img)
    
    try:
        font = ImageFont.load_default()
    except Exception:
        font = None
        
    for col in _rain_cols:
        col["y"] += col["speed"]
        if col["y"] > 240:
            col["y"] = -100
            col["speed"] = random.uniform(2.0, 5.0)
            
        y = col["y"]
        for idx, char in enumerate(col["chars"]):
            cy = y + idx * 10
            if -10 < cy < 250:
                alpha = int(255 * ((idx + 1) / len(col["chars"])))
                color = (0, alpha, int(alpha * 0.3))
                if font:
                    d.text((col["x"], cy), char, fill=color, font=font)
                else:
                    d.rectangle([col["x"], cy, col["x"] + 5, cy + 5], fill=color)
                    
            if random.random() < 0.05:
                col["chars"][idx] = random.choice(["0", "1"])
                
    return img


def _render_starfield_frame(bezel, mask, now):
    global _starfield_stars
    if not _starfield_stars:
        _init_starfield()
        
    img = Image.new("RGB", (240, 240), (0, 5, 2))
    d = ImageDraw.Draw(img)
    
    for star in _starfield_stars:
        star["z"] -= star["speed"]
        if star["z"] <= 1.0:
            star["x"] = random.uniform(-120, 120)
            star["y"] = random.uniform(-120, 120)
            star["z"] = 120.0
            
        k = 100.0 / star["z"]
        px = int(120.0 + star["x"] * k)
        py = int(120.0 + star["y"] * k)
        
        if 0 <= px < 240 and 0 <= py < 240:
            size = max(1, int(3 * (1.0 - star["z"] / 120.0)))
            brightness = int(255 * (1.0 - star["z"] / 120.0))
            d.ellipse([px - size, py - size, px + size, py + size], fill=(0, brightness, int(brightness * 0.4)))
            
    return img


def _render_oscilloscope_frame(bezel, mask, now):
    img = Image.new("RGB", (240, 240), (0, 10, 4))
    d = ImageDraw.Draw(img)
    
    for x in range(20, 240, 40):
        d.line([(x, 0), (x, 240)], fill=(0, 25, 10), width=1)
    for y in range(20, 240, 40):
        d.line([(0, y), (240, y)], fill=(0, 25, 10), width=1)
        
    pts1 = []
    pts2 = []
    for x in range(0, 241, 4):
        y1 = 120.0 + 35.0 * math.sin(x * 0.05 + now * 5.0) + 10.0 * math.sin(x * 0.12 - now * 2.0)
        y2 = 120.0 + 20.0 * math.cos(x * 0.08 - now * 4.0) + 8.0 * math.sin(x * 0.03 + now * 3.0)
        pts1.append((x, y1))
        pts2.append((x, y2))
        
    d.line(pts1, fill=(0, 180, 50), width=2)
    d.line(pts2, fill=(0, 240, 100), width=1)
    return img


def _render_game_of_life_frame(bezel, mask, now):
    global _gol_grid, _gol_last_grids
    if _gol_grid is None:
        _init_game_of_life()
        
    if not hasattr(_render_game_of_life_frame, "last_step"):
        _render_game_of_life_frame.last_step = 0.0
        
    if now - _render_game_of_life_frame.last_step > 0.1:
        _render_game_of_life_frame.last_step = now
        
        grid_tuple = tuple(tuple(row) for row in _gol_grid)
        _gol_last_grids.append(grid_tuple)
        if len(_gol_last_grids) > 6:
            _gol_last_grids.pop(0)
            
        is_static = len(_gol_last_grids) >= 6 and (
            _gol_last_grids[-1] == _gol_last_grids[-2] or
            _gol_last_grids[-1] == _gol_last_grids[-3] or
            _gol_last_grids[-1] == _gol_last_grids[-4]
        )
        total_cells = sum(sum(row) for row in _gol_grid)
        if total_cells < 5 or is_static:
            _init_game_of_life()
            
        new_grid = [[0 for _ in range(24)] for _ in range(24)]
        for r in range(24):
            for c in range(24):
                neighbors = 0
                for dr in [-1, 0, 1]:
                    for dc in [-1, 0, 1]:
                        if dr == 0 and dc == 0:
                            continue
                        nr, nc = (r + dr) % 24, (c + dc) % 24
                        neighbors += _gol_grid[nr][nc]
                if _gol_grid[r][c] == 1:
                    new_grid[r][c] = 1 if neighbors in [2, 3] else 0
                else:
                    new_grid[r][c] = 1 if neighbors == 3 else 0
        _gol_grid = new_grid
        
    img = Image.new("RGB", (240, 240), (0, 8, 3))
    d = ImageDraw.Draw(img)
    
    for r in range(24):
        for c in range(24):
            if _gol_grid[r][c] == 1:
                d.rectangle([c * 10 + 1, r * 10 + 1, c * 10 + 9, r * 10 + 9], fill=(0, 220, 80))
            else:
                d.rectangle([c * 10, r * 10, c * 10 + 10, r * 10 + 10], outline=(0, 20, 5), width=1)
                
    return img


def _render_radar_frame(bezel, mask, now):
    global _radar_blips
    if not _radar_blips:
        _init_radar()
        
    img = Image.new("RGB", (240, 240), (0, 10, 4))
    d = ImageDraw.Draw(img)
    
    sweep_angle = (now * 150.0) % 360.0
    sweep_rad = math.radians(sweep_angle)
    
    for r in range(30, 120, 30):
        d.ellipse([120 - r, 120 - r, 120 + r, 120 + r], outline=(0, 45, 15), width=1)
        
    d.line([(10, 120), (230, 120)], fill=(0, 45, 15), width=1)
    d.line([(120, 10), (120, 230)], fill=(0, 45, 15), width=1)
    
    sx = 120.0 + 110.0 * math.cos(sweep_rad)
    sy = 120.0 + 110.0 * math.sin(sweep_rad)
    d.line([(120, 120), (sx, sy)], fill=(0, 255, 100), width=2)
    
    for step in range(1, 15):
        a_trail = math.radians(sweep_angle - step * 2)
        tx = 120.0 + 110.0 * math.cos(a_trail)
        ty = 120.0 + 110.0 * math.sin(a_trail)
        val = int(200 * (1.0 - step / 15.0))
        d.line([(120, 120), (tx, ty)], fill=(0, val, int(val * 0.3)), width=1)
        
    for blip in _radar_blips:
        diff = abs(sweep_rad - blip["angle"]) % (math.pi * 2)
        if diff < 0.05:
            blip["brightness"] = 255.0
        else:
            blip["brightness"] = max(0.0, blip["brightness"] - 2.5)
            
        if blip["brightness"] > 0:
            val = int(blip["brightness"])
            d.ellipse([blip["x"] - 4, blip["y"] - 4, blip["x"] + 4, blip["y"] + 4], fill=(0, val, int(val * 0.4)))
            d.ellipse([blip["x"] - 7, blip["y"] - 7, blip["x"] + 7, blip["y"] + 7], outline=(0, int(val * 0.6), 0), width=1)
            
    return img


def _render_warp_core_frame(bezel, mask, now):
    img = Image.new("RGB", (240, 240), (0, 10, 5))
    d = ImageDraw.Draw(img)
    
    core_r = 15.0 + 4.0 * math.sin(now * 8.0)
    d.ellipse([120 - core_r, 120 - core_r, 120 + core_r, 120 + core_r], fill=(0, 255, 120))
    d.ellipse([120 - core_r + 4, 120 - core_r + 4, 120 + core_r - 4, 120 + core_r - 4], fill=(150, 255, 200))
    
    for i in range(5):
        t = (now * 45.0 + i * 25.0) % 110.0
        r = core_r + t
        if r < 115.0:
            alpha = int(255 * (1.0 - r / 115.0))
            d.ellipse([120 - r, 120 - r, 120 + r, 120 + r], outline=(0, alpha, int(alpha * 0.4)), width=1)
            
    return img


def _render_circuit_maze_frame(bezel, mask, now):
    global _maze_grid, _maze_last_flip
    if not _maze_grid or len(_maze_grid) != 24:
        _init_circuit_maze()
        
    if now - _maze_last_flip > 0.2:
        _maze_last_flip = now
        for _ in range(2):
            r = random.randint(0, 23)
            c = random.randint(0, 23)
            _maze_grid[r][c] = 1 - _maze_grid[r][c]
        
    img = Image.new("RGB", (240, 240), (0, 10, 4))
    d = ImageDraw.Draw(img)
    
    for r in range(24):
        for c in range(24):
            x1 = c * 10
            y1 = r * 10
            x2 = x1 + 10
            y2 = y1 + 10
            if _maze_grid[r][c] == 0:
                d.line([(x1, y1), (x2, y2)], fill=(0, 180, 60), width=1)
            else:
                d.line([(x2, y1), (x1, y2)], fill=(0, 180, 60), width=1)
                
    return img


def _render_double_helix_frame(bezel, mask, now):
    img = Image.new("RGB", (240, 240), (0, 8, 3))
    d = ImageDraw.Draw(img)
    
    min_y, max_y = 10, 230
    helix_w = 45.0
    
    for y in range(min_y, max_y + 1, 6):
        phase = (y * 0.08) - (now * 4.0)
        x_offset1 = helix_w * math.sin(phase)
        x_offset2 = helix_w * math.sin(phase + math.pi)
        
        x1 = 120 + x_offset1
        x2 = 120 + x_offset2
        
        z1 = math.cos(phase)
        z2 = math.cos(phase + math.pi)
        
        d.line([(x1, y), (x2, y)], fill=(0, 80, 30), width=1)
        
        b1 = int(140 + 115 * z1)
        b2 = int(140 + 115 * z2)
        
        d.ellipse([x1 - 3, y - 3, x1 + 3, y + 3], fill=(0, b1, int(b1 * 0.4)))
        d.ellipse([x2 - 3, y - 3, x2 + 3, y + 3], fill=(0, b2, int(b2 * 0.4)))
        
    return img


def _render_spinning_rings_frame(bezel, mask, now):
    img = Image.new("RGB", (240, 240), (0, 8, 3))
    d = ImageDraw.Draw(img)
    
    for ring, (r, speed, col) in enumerate([
        (35, 1.2, (0, 200, 70)),
        (65, -0.8, (0, 160, 50)),
        (95, 0.5, (0, 240, 80))
    ]):
        a = (now * speed) % (math.pi * 2)
        d.ellipse([120 - r, 120 - r, 120 + r, 120 + r], outline=col, width=1)
        
        dot_x = 120 + r * math.cos(a)
        dot_y = 120 + r * math.sin(a)
        d.ellipse([dot_x - 4, dot_y - 4, dot_x + 4, dot_y + 4], fill=(0, 255, 120))
        
    return img


def _render_wireframe_cube_frame(bezel, mask, now):
    img = Image.new("RGB", (240, 240), (0, 8, 3))
    d = ImageDraw.Draw(img)
    
    ax = now * 0.7
    ay = now * 1.1
    az = now * 0.4
    
    nodes = [
        (-40, -40, -40), (40, -40, -40), (40, 40, -40), (-40, 40, -40),
        (-40, -40, 40), (40, -40, 40), (40, 40, 40), (-40, 40, 40)
    ]
    edges = [
        (0, 1), (1, 2), (2, 3), (3, 0),
        (4, 5), (5, 6), (6, 7), (7, 4),
        (0, 4), (1, 5), (2, 6), (3, 7)
    ]
    
    proj = []
    for x, y, z in nodes:
        # Rotate X
        y1 = y * math.cos(ax) - z * math.sin(ax)
        z1 = y * math.sin(ax) + z * math.cos(ax)
        # Rotate Y
        x2 = x * math.cos(ay) + z1 * math.sin(ay)
        z2 = -x * math.sin(ay) + z1 * math.cos(ay)
        # Rotate Z
        x3 = x2 * math.cos(az) - y1 * math.sin(az)
        y3 = x2 * math.sin(az) + y1 * math.cos(az)
        
        fov = 180.0
        distance = 180.0
        f = fov / (distance + z2)
        px = 120 + x3 * f
        py = 120 + y3 * f
        proj.append((px, py))
        
    for i, j in edges:
        d.line([proj[i], proj[j]], fill=(0, 200, 70), width=2)
    for px, py in proj:
        d.ellipse([px - 3, py - 3, px + 3, py + 3], fill=(0, 255, 120))
        
    return img


def _render_bouncing_cog_frame(bezel, mask, now):
    global _bc_x, _bc_y, _bc_dx, _bc_dy, _bc_angle
    
    _bc_x += _bc_dx
    _bc_y += _bc_dy
    _bc_angle = (_bc_angle + 3.0) % 360.0
    
    r_cog = 32.0
    dist_sq = (_bc_x - 120.0) ** 2 + (_bc_y - 120.0) ** 2
    if dist_sq >= (110.0 - r_cog) ** 2:
        nx = (_bc_x - 120.0) / (math.sqrt(dist_sq) or 1.0)
        ny = (_bc_y - 120.0) / (math.sqrt(dist_sq) or 1.0)
        dot = _bc_dx * nx + _bc_dy * ny
        _bc_dx -= 2.0 * dot * nx
        _bc_dy -= 2.0 * dot * ny
        _bc_x = 120.0 + nx * (108.0 - r_cog)
        _bc_y = 120.0 + ny * (108.0 - r_cog)
        
    img = Image.new("RGB", (240, 240), (0, 8, 3))
    d = ImageDraw.Draw(img)
    
    cx, cy = int(_bc_x), int(_bc_y)
    rad_rad = math.radians(_bc_angle)
    
    # Outer ring
    d.ellipse([cx - 28, cy - 28, cx + 28, cy + 28], outline=(0, 220, 80), width=2)
    d.ellipse([cx - 14, cy - 14, cx + 14, cy + 14], outline=(0, 220, 80), width=1)
    
    # Teeth
    for t_idx in range(8):
        a = rad_rad + t_idx * (math.pi / 4.0)
        tx1 = cx + 28 * math.cos(a - 0.15)
        ty1 = cy + 28 * math.sin(a - 0.15)
        tx2 = cx + 35 * math.cos(a)
        ty2 = cy + 35 * math.sin(a)
        tx3 = cx + 28 * math.cos(a + 0.15)
        ty3 = cy + 28 * math.sin(a + 0.15)
        d.polygon([(tx1, ty1), (tx2, ty2), (tx3, ty3)], fill=(0, 220, 80))
        
    return img


def _render_fractal_tree_frame(bezel, mask, now):
    img = Image.new("RGB", (240, 240), (0, 8, 3))
    d = ImageDraw.Draw(img)
    
    wind = 0.15 * math.sin(now * 1.5)
    
    def _draw_branch(x, y, angle, length, depth):
        if depth <= 0 or length < 2:
            return
        x2 = x + length * math.cos(angle)
        y2 = y + length * math.sin(angle)
        
        green_val = int(80 + 175 * (depth / 6.0))
        d.line([(x, y), (x2, y2)], fill=(0, green_val, 40), width=max(1, depth // 2))
        
        _draw_branch(x2, y2, angle - 0.45 + wind, length * 0.72, depth - 1)
        _draw_branch(x2, y2, angle + 0.45 + wind, length * 0.72, depth - 1)
        
    _draw_branch(120, 220, -math.pi / 2.0, 52.0, 6)
    return img


def _render_hud_status_frame(bezel, mask, now):
    img = Image.new("RGB", (240, 240), (0, 8, 3))
    d = ImageDraw.Draw(img)
    
    try:
        font = ImageFont.load_default()
    except Exception:
        font = None
        
    d.ellipse([10, 10, 230, 230], outline=(0, 100, 35), width=1)
    d.ellipse([20, 20, 220, 220], outline=(0, 60, 20), width=1)
    
    # Ticks
    for deg in range(0, 360, 30):
        rad = math.radians(deg)
        x1 = 120 + 100 * math.cos(rad)
        y1 = 120 + 100 * math.sin(rad)
        x2 = 120 + 110 * math.cos(rad)
        y2 = 120 + 110 * math.sin(rad)
        d.line([(x1, y1), (x2, y2)], fill=(0, 180, 60), width=1)
        
    if font:
        d.text((65, 60), "OMEGA-7 COGITATOR", fill=(0, 220, 80), font=font)
        d.text((70, 85), f"UPTIME: {int(now)}s", fill=(0, 180, 60), font=font)
        
        v1 = int(50 + 40 * math.sin(now * 2.0))
        v2 = int(60 + 35 * math.cos(now * 1.5))
        d.text((70, 115), f"CORE-1 LOAD: {v1}%", fill=(0, 220, 80), font=font)
        d.text((70, 135), f"CORE-2 LOAD: {v2}%", fill=(0, 220, 80), font=font)
        d.text((70, 160), "STATUS: VIGILANT", fill=(0, 255, 100), font=font)
        
    return img


def _render_orbitals_frame(bezel, mask, now):
    global _orbital_particles
    if not _orbital_particles:
        _init_orbitals()
        
    img = Image.new("RGB", (240, 240), (0, 8, 3))
    d = ImageDraw.Draw(img)
    
    d.ellipse([110, 110, 130, 130], fill=(0, 255, 100))
    
    for p in _orbital_particles:
        t = now * p["speed"]
        ox = p["radius_x"] * math.cos(t)
        oy = p["radius_y"] * math.sin(t)
        
        rot = p["rot"]
        rx = ox * math.cos(rot) - oy * math.sin(rot)
        ry = ox * math.sin(rot) + oy * math.cos(rot)
        
        px = 120 + rx
        py = 120 + ry
        
        d.ellipse([px - 4, py - 4, px + 4, py + 4], fill=(0, 220, 80))
        d.ellipse([120 - p["radius_x"], 120 - p["radius_y"], 120 + p["radius_x"], 120 + p["radius_y"]], outline=(0, 50, 20), width=1)
        
    return img


def _render_spectrum_bars_frame(bezel, mask, now):
    global _spectrum_heights, _spectrum_targets, _spectrum_last_update
    if not _spectrum_heights:
        _init_spectrum_bars()
        
    if now - _spectrum_last_update > 0.15:
        _spectrum_last_update = now
        _spectrum_targets = [random.uniform(10, 160) for _ in range(12)]
        
    if len(_spectrum_heights) != 12:
        _spectrum_heights = [random.uniform(10, 160) for _ in range(12)]
        
    for i in range(12):
        _spectrum_heights[i] += (_spectrum_targets[i] - _spectrum_heights[i]) * 0.35
        
    img = Image.new("RGB", (240, 240), (0, 10, 4))
    d = ImageDraw.Draw(img)
    
    start_x = 14
    for i in range(12):
        h = int(_spectrum_heights[i])
        bx1 = start_x + i * 18
        bx2 = bx1 + 14
        by2 = 220
        by1 = by2 - h
        
        for sy in range(by2, by1 - 1, -6):
            d.rectangle([bx1, sy - 4, bx2, sy], fill=(0, 230, 80))
            
    return img


def _render_plasma_frame(bezel, mask, now):
    """Sine-wave interference plasma – subdued phosphor green & amber waves."""
    x = np.linspace(0, 2 * math.pi, 240)
    y = np.linspace(0, 2 * math.pi, 240)
    xx, yy = np.meshgrid(x, y)
    t = now * 1.2
    v = (np.sin(xx + t) + np.sin(yy + t * 0.7)
         + np.sin((xx + yy) * 0.5 + t * 0.9)
         + np.sin(np.sqrt(xx**2 + yy**2) + t)) / 4.0
    v = (v + 1.0) / 2.0
    r = (v * 40).clip(0, 255).astype(np.uint8)
    g = (v * 210 + 20).clip(0, 255).astype(np.uint8)
    b = (v * 50).clip(0, 255).astype(np.uint8)
    arr = np.stack([r, g, b], axis=-1)
    return Image.fromarray(arr, mode="RGB")


def _render_lissajous_frame(bezel, mask, now):
    """Lissajous curve tracer – subdued phosphor green & amber figures."""
    img = Image.new("RGB", (240, 240), (0, 8, 3))
    d = ImageDraw.Draw(img)
    a, b_freq, delta = 3, 2, now * 0.4
    pts = []
    for i in range(600):
        t = i * math.pi * 2 / 600
        x = int(110 * math.sin(a * t + delta) + 120)
        y = int(110 * math.sin(b_freq * t) + 120)
        pts.append((x, y))
    for i in range(len(pts) - 1):
        frac = i / len(pts)
        intensity = abs(math.sin(frac * math.pi + now))
        g = int(160 + 95 * intensity)
        r = int(20 * intensity)
        b = int(30 * intensity)
        d.line([pts[i], pts[i+1]], fill=(r, g, b), width=2)
    return img


def _render_voronoi_frame(bezel, mask, now):
    global _voronoi_sites
    if not _voronoi_sites:
        _init_voronoi()
    for s in _voronoi_sites:
        s["x"] = (s["x"] + s["dx"]) % 240
        s["y"] = (s["y"] + s["dy"]) % 240
    xs = np.array([s["x"] for s in _voronoi_sites])
    ys = np.array([s["y"] for s in _voronoi_sites])
    colors = np.array([[s["c"][0], s["c"][1], s["c"][2]] for s in _voronoi_sites], dtype=np.uint8)
    px = np.arange(240)
    py = np.arange(240)
    gx, gy = np.meshgrid(px, py)
    dists = np.sqrt((gx[:,:,None] - xs)**2 + (gy[:,:,None] - ys)**2)
    nearest = np.argmin(dists, axis=2)
    arr = colors[nearest]
    arr = (arr * 0.7).clip(0, 255).astype(np.uint8)
    return Image.fromarray(arr, mode="RGB")


def _render_data_stream_frame(bezel, mask, now):
    global _data_stream_lines
    if not _data_stream_lines:
        _init_data_stream()
    img = Image.new("RGB", (240, 240), (0, 8, 3))
    d = ImageDraw.Draw(img)
    try:
        font = ImageFont.load_default()
    except Exception:
        font = None
    for line in _data_stream_lines:
        line["y"] = (line["y"] + line["speed"]) % 250
        y = line["y"]
        text = line["text"]
        for idx, ch in enumerate(text):
            xp = 10 + idx * 11
            alpha = max(30, int(230 * math.sin(idx * 0.3 + now * 2.0)))
            c = (0, alpha, int(alpha * 0.3))
            if font:
                d.text((xp, y), ch, fill=c, font=font)
    return img


def _render_mandala_frame(bezel, mask, now):
    """Rotating concentric mandala geometry – subdued Mechanicus phosphors."""
    img = Image.new("RGB", (240, 240), (0, 8, 3))
    d = ImageDraw.Draw(img)
    for ring in range(1, 8):
        r = ring * 14
        n_pts = ring * 6
        base_angle = now * (0.3 if ring % 2 == 0 else -0.3) * (ring * 0.2)
        t = now * 0.5
        intensity = abs(math.sin(ring * 0.5 + t))
        red = int(20 * intensity) if ring % 3 != 0 else int(160 * intensity)
        grn = int(140 + 115 * intensity)
        blu = int(40 * intensity)
        pts = []
        for i in range(n_pts):
            a = base_angle + i * 2 * math.pi / n_pts
            pts.append((120 + r * math.cos(a), 120 + r * math.sin(a)))
        if len(pts) > 2:
            d.polygon(pts, outline=(red, grn, blu))
    return img


def _render_rune_wheel_frame(bezel, mask, now):
    """Spinning elder rune characters around concentric circles – subdued green/amber."""
    img = Image.new("RGB", (240, 240), (0, 8, 3))
    d = ImageDraw.Draw(img)
    try:
        font = ImageFont.load_default()
    except Exception:
        font = None
    runes = list("ᚠᚢᚦᚨᚱᚲᚷᚹᚺᚾᛁᛃᛇᛈᛉᛊᛏᛒᛖᛗᛚᛜᛞᛟ")
    for ring_idx, (radius, speed, count) in enumerate([(40, 0.4, 8), (70, -0.25, 12), (100, 0.15, 16)]):
        for i in range(count):
            a = now * speed + i * 2 * math.pi / count
            x = int(120 + radius * math.cos(a))
            y = int(120 + radius * math.sin(a))
            t = now * 0.5
            intensity = abs(math.sin(ring_idx * 0.7 + t + i * 0.2))
            if ring_idx == 1:
                r, g, b = int(180 * intensity), int(100 * intensity), 0
            else:
                r, g, b = int(20 * intensity), int(160 + 95 * intensity), int(40 * intensity)
            rune = runes[(ring_idx * count + i) % len(runes)]
            if font:
                d.text((x - 4, y - 4), rune, fill=(r, g, b), font=font)
    return img


def _render_glitch_frame(bezel, mask, now):
    """Digital glitch / corruption aesthetic – subdued Mechanicus CRT noise."""
    img = Image.new("RGB", (240, 240), (0, 8, 3))
    d = ImageDraw.Draw(img)
    for _ in range(random.randint(4, 14)):
        y = random.randint(0, 239)
        h = random.randint(1, 8)
        xoff = random.randint(-40, 40)
        d.rectangle([0, y, 239, y + h], fill=(0, random.randint(15, 35), random.randint(5, 15)))
        d.rectangle([max(0, xoff), y, min(239, 239 + xoff), y + h], fill=random.choice([(180, 0, 0), (0, 200, 60), (180, 100, 0)]))
    for _ in range(random.randint(20, 60)):
        x = random.randint(0, 239)
        y = random.randint(0, 239)
        c = random.choice([(0, 255, 100), (0, 180, 50), (220, 120, 0), (180, 0, 0)])
        d.point((x, y), fill=c)
    for _ in range(random.randint(1, 4)):
        x = random.randint(0, 239)
        d.line([(x, 0), (x, 239)], fill=(0, random.randint(120, 220), 40), width=1)
    return img


def _render_dna_helix_frame(bezel, mask, now):
    """Rotating double helix ribbons scrolling vertically – subdued green & amber."""
    img = Image.new("RGB", (240, 240), (0, 8, 3))
    d = ImageDraw.Draw(img)
    for y in range(0, 240, 3):
        t = y * 0.06 + now * 2.0
        x1 = int(120 + 60 * math.sin(t))
        x2 = int(120 + 60 * math.sin(t + math.pi))
        frac = (math.sin(t) + 1) / 2
        c1 = (0, int(150 + 105 * frac), int(30 + 40 * frac))
        c2 = (int(160 + 80 * (1 - frac)), int(80 + 40 * (1 - frac)), 0)
        d.ellipse([x1 - 3, y - 3, x1 + 3, y + 3], fill=c1)
        d.ellipse([x2 - 3, y - 3, x2 + 3, y + 3], fill=c2)
        if y % 20 < 3:
            d.line([(x1, y), (x2, y)], fill=(0, 60, 20), width=1)
    return img


def _render_neural_net_frame(bezel, mask, now):
    global _neural_pulses
    if not _neural_nodes:
        _init_neural_net()
    img = Image.new("RGB", (240, 240), (0, 8, 3))
    d = ImageDraw.Draw(img)
    for i, j in _neural_edges:
        d.line([(int(_neural_nodes[i]["x"]), int(_neural_nodes[i]["y"])),
                (int(_neural_nodes[j]["x"]), int(_neural_nodes[j]["y"]))],
               fill=(0, 45, 15), width=1)
    if random.random() < 0.15 and _neural_edges:
        e = random.choice(_neural_edges)
        _neural_pulses.append({"edge": e, "t": 0.0})
    new_pulses = []
    for p in _neural_pulses:
        p["t"] += 0.04
        if p["t"] < 1.0:
            i, j = p["edge"]
            x = int(_neural_nodes[i]["x"] * (1 - p["t"]) + _neural_nodes[j]["x"] * p["t"])
            y = int(_neural_nodes[i]["y"] * (1 - p["t"]) + _neural_nodes[j]["y"] * p["t"])
            bright = int(255 * (1 - abs(p["t"] - 0.5) * 2))
            d.ellipse([x-4, y-4, x+4, y+4], fill=(int(bright * 0.8), bright, int(bright * 0.2)))
            new_pulses.append(p)
    _neural_pulses = new_pulses
    for n in _neural_nodes:
        d.ellipse([int(n["x"]) - 3, int(n["y"]) - 3, int(n["x"]) + 3, int(n["y"]) + 3],
                  fill=(0, 200, 70))
    return img


def _render_gravity_well_frame(bezel, mask, now):
    """Particles spiraling into a singularity at centre – subdued green/amber."""
    img = Image.new("RGB", (240, 240), (0, 8, 3))
    d = ImageDraw.Draw(img)
    n = 80
    for i in range(n):
        phase = i / n * 2 * math.pi
        t = (now * 0.4 + phase) % (2 * math.pi)
        r_orbit = 100 * (1 - t / (2 * math.pi)) + 2
        spiral_angle = phase + now * 0.6 + t * 3
        x = int(120 + r_orbit * math.cos(spiral_angle))
        y = int(120 + r_orbit * math.sin(spiral_angle))
        bright = int(255 * (1 - r_orbit / 100))
        c = (0, bright, int(bright * 0.3))
        d.ellipse([x-1, y-1, x+1, y+1], fill=c)
    for rr in [12, 8, 4, 2]:
        alpha = int(255 * (1 - rr / 12))
        d.ellipse([120-rr, 120-rr, 120+rr, 120+rr], fill=(alpha, int(alpha*0.5), 0))
    return img


def _render_void_shield_frame(bezel, mask, now):
    """Pulsing forcefield concentric barrier – subdued green & amber."""
    img = Image.new("RGB", (240, 240), (0, 8, 3))
    d = ImageDraw.Draw(img)
    pulse = math.sin(now * 3.0) * 8
    for r in [40, 70, 100]:
        radius = r + pulse
        intensity = int(160 + 90 * math.sin(now * 2.0 + r * 0.1))
        d.ellipse([120 - radius, 120 - radius, 120 + radius, 120 + radius],
                  outline=(0, intensity, int(intensity * 0.3)), width=2)
    return img


def _render_hex_grid_frame(bezel, mask, now):
    global _hex_grid_cells, _hex_last_flash
    if not _hex_grid_cells:
        _init_hex_grid()
    img = Image.new("RGB", (240, 240), (0, 8, 3))
    d = ImageDraw.Draw(img)
    if now - _hex_last_flash > 0.08:
        _hex_last_flash = now
        for _ in range(random.randint(1, 3)):
            cell = random.choice(_hex_grid_cells)
            cell["flash"] = 1.0
    for cell in _hex_grid_cells:
        cell["flash"] = max(0.0, cell["flash"] - 0.06)
        f = cell["flash"]
        r = int(220 * f)
        g = int(60 + 195 * f)
        b = int(20 * (1 - f))
        s = cell["size"]
        x, y = cell["x"], cell["y"]
        pts = [(x + s * math.cos(math.radians(60 * i + 30)), y + s * math.sin(math.radians(60 * i + 30))) for i in range(6)]
        d.polygon(pts, outline=(r, g, b))
    return img


def _render_kaleidoscope_frame(bezel, mask, now):
    """Radially mirrored mandala pattern – subdued Mechanicus green/amber/crimson."""
    n_segments = 8
    img = Image.new("RGB", (240, 240), (0, 8, 3))
    d = ImageDraw.Draw(img)
    for seg in range(n_segments):
        base_a = seg * (2 * math.pi / n_segments) + now * 0.2
        for i in range(30):
            t = i / 30
            rr = 10 + t * 100
            a1 = base_a + t * 1.2 * math.sin(now * 0.7)
            a2 = base_a + (t + 0.1) * 1.2 * math.sin(now * 0.7)
            x1 = int(120 + rr * math.cos(a1))
            y1 = int(120 + rr * math.sin(a1))
            x2 = int(120 + (rr + 4) * math.cos(a2))
            y2 = int(120 + (rr + 4) * math.sin(a2))
            cycle = (now * 0.5 + seg * 0.25 + t) % 3.0
            if cycle < 1.0:
                col = (0, int(160 + 95 * cycle), int(30 + 40 * cycle))
            elif cycle < 2.0:
                frac = cycle - 1.0
                col = (int(180 * frac), int(120 * frac), 0)
            else:
                frac = cycle - 2.0
                col = (int(160 * (1 - frac)), 0, 0)
            d.line([(x1, y1), (x2, y2)], fill=col, width=2)
    return img


def _render_particle_burst_frame(bezel, mask, now):
    global _pburst_particles
    img = Image.new("RGB", (240, 240), (0, 8, 3))
    d = ImageDraw.Draw(img)
    if not hasattr(_render_particle_burst_frame, "last_burst"):
        _render_particle_burst_frame.last_burst = 0.0
    if now - _render_particle_burst_frame.last_burst > 0.8:
        _render_particle_burst_frame.last_burst = now
        n = random.randint(20, 40)
        bx = random.uniform(60, 180)
        by = random.uniform(60, 180)
        p_type = random.choice([0, 0, 0, 1, 1, 2])
        for _ in range(n):
            a = random.uniform(0, 2 * math.pi)
            spd = random.uniform(1.5, 5.0)
            _pburst_particles.append({"x": bx, "y": by, "vx": math.cos(a) * spd,
                                       "vy": math.sin(a) * spd, "life": 1.0, "type": p_type})
    new_p = []
    for p in _pburst_particles:
        p["x"] += p["vx"]
        p["y"] += p["vy"]
        p["vy"] += 0.08
        p["life"] -= 0.025
        if p["life"] > 0:
            alpha = p["life"]
            if p["type"] == 0:
                r, g, b = 0, int(230 * alpha), int(60 * alpha)
            elif p["type"] == 1:
                r, g, b = int(220 * alpha), int(130 * alpha), 0
            else:
                r, g, b = int(200 * alpha), 0, 0
            col = (r, g, b)
            d.ellipse([int(p["x"]) - 2, int(p["y"]) - 2, int(p["x"]) + 2, int(p["y"]) + 2], fill=col)
            new_p.append(p)
    _pburst_particles = new_p
    return img


def _render_asteroids_frame(bezel, mask, now):
    """Vector Arcade Asteroids Simulator – Adeptus Mechanicus phosphor edition."""
    global _ast_ship, _ast_asteroids, _ast_bullets, _ast_sparks, _ast_score, _ast_last_shot

    if _ast_ship is None or not _ast_asteroids:
        _init_asteroids()

    img = Image.new("RGB", (240, 240), (0, 8, 3))
    d = ImageDraw.Draw(img)

    # 1. Update AI Pilot Ship behavior
    # Find nearest asteroid to target
    target_ast = None
    min_d = 9999.0
    for ast in _ast_asteroids:
        dist = math.hypot(ast["x"] - _ast_ship["x"], ast["y"] - _ast_ship["y"])
        if dist < min_d:
            min_d = dist
            target_ast = ast

    if target_ast:
        target_angle = math.atan2(target_ast["y"] - _ast_ship["y"], target_ast["x"] - _ast_ship["x"])
        # Smoothly rotate ship towards target
        angle_diff = (target_angle - _ast_ship["angle"] + math.pi) % (2 * math.pi) - math.pi
        _ast_ship["angle"] += max(-0.12, min(0.12, angle_diff))
        
        # Thrust towards target if not too close
        if min_d > 40:
            _ast_ship["vx"] += math.cos(_ast_ship["angle"]) * 0.15
            _ast_ship["vy"] += math.sin(_ast_ship["angle"]) * 0.15
            _ast_ship["thrusting"] = True
        else:
            _ast_ship["thrusting"] = False

        # Fire weapon if aligned with target
        if abs(angle_diff) < 0.25 and (now - _ast_last_shot > 0.25):
            _ast_last_shot = now
            b_spd = 6.0
            bx = _ast_ship["x"] + math.cos(_ast_ship["angle"]) * 10
            by = _ast_ship["y"] + math.sin(_ast_ship["angle"]) * 10
            b_vx = _ast_ship["vx"] + math.cos(_ast_ship["angle"]) * b_spd
            b_vy = _ast_ship["vy"] + math.sin(_ast_ship["angle"]) * b_spd
            _ast_bullets.append({"x": bx, "y": by, "vx": b_vx, "vy": b_vy, "life": 40})

    # Apply drag & update ship position with screen wrap
    _ast_ship["vx"] *= 0.96
    _ast_ship["vy"] *= 0.96
    _ast_ship["x"] = (_ast_ship["x"] + _ast_ship["vx"]) % 240
    _ast_ship["y"] = (_ast_ship["y"] + _ast_ship["vy"]) % 240

    # 2. Update Bullets & Collisions
    new_bullets = []
    for b in _ast_bullets:
        b["x"] = (b["x"] + b["vx"]) % 240
        b["y"] = (b["y"] + b["vy"]) % 240
        b["life"] -= 1
        hit = False

        # Check collision with asteroids
        for ast in list(_ast_asteroids):
            if math.hypot(b["x"] - ast["x"], b["y"] - ast["y"]) <= ast["radius"]:
                hit = True
                _ast_score += 100
                # Spawn explosion sparks
                for _ in range(random.randint(6, 12)):
                    sp_angle = random.uniform(0, 2 * math.pi)
                    sp_spd = random.uniform(1.0, 4.0)
                    sp_col = random.choice([(0, 255, 100), (220, 140, 20), (200, 30, 30)])
                    _ast_sparks.append({
                        "x": ast["x"], "y": ast["y"],
                        "vx": math.cos(sp_angle) * sp_spd, "vy": math.sin(sp_angle) * sp_spd,
                        "life": 1.0, "col": sp_col
                    })

                # Split asteroid if large enough
                _ast_asteroids.remove(ast)
                if ast["radius"] >= 14:
                    for _ in range(2):
                        split_rad = ast["radius"] * 0.6
                        _ast_asteroids.append({
                            "x": ast["x"] + random.uniform(-5, 5),
                            "y": ast["y"] + random.uniform(-5, 5),
                            "vx": random.uniform(-1.8, 1.8),
                            "vy": random.uniform(-1.8, 1.8),
                            "radius": split_rad,
                            "rot": random.uniform(0, math.pi * 2),
                            "rot_spd": random.uniform(-0.06, 0.06),
                            "poly": _create_asteroid_polygon(split_rad)
                        })
                break

        if not hit and b["life"] > 0:
            new_bullets.append(b)

    _ast_bullets = new_bullets

    # Respawn asteroids if all destroyed
    if len(_ast_asteroids) == 0:
        for _ in range(4):
            rad = random.uniform(16, 24)
            _ast_asteroids.append({
                "x": random.uniform(20, 220), "y": random.uniform(20, 220),
                "vx": random.uniform(-1.2, 1.2), "vy": random.uniform(-1.2, 1.2),
                "radius": rad, "rot": random.uniform(0, math.pi * 2),
                "rot_spd": random.uniform(-0.04, 0.04),
                "poly": _create_asteroid_polygon(rad)
            })

    # 3. Update Asteroids
    for ast in _ast_asteroids:
        ast["x"] = (ast["x"] + ast["vx"]) % 240
        ast["y"] = (ast["y"] + ast["vy"]) % 240
        ast["rot"] = (ast["rot"] + ast["rot_spd"]) % (2 * math.pi)

    # 4. Render Asteroids
    for ast in _ast_asteroids:
        cos_r = math.cos(ast["rot"])
        sin_r = math.sin(ast["rot"])
        world_pts = []
        for px, py in ast["poly"]:
            rx = px * cos_r - py * sin_r + ast["x"]
            ry = px * sin_r + py * cos_r + ast["y"]
            world_pts.append((rx, ry))
        if len(world_pts) > 2:
            d.polygon(world_pts, outline=(0, 200, 70), width=1)

    # 5. Render Bullets
    for b in _ast_bullets:
        d.ellipse([b["x"] - 2, b["y"] - 2, b["x"] + 2, b["y"] + 2], fill=(0, 255, 120))

    # 6. Render Sparks
    new_sparks = []
    for sp in _ast_sparks:
        sp["x"] += sp["vx"]
        sp["y"] += sp["vy"]
        sp["life"] -= 0.05
        if sp["life"] > 0:
            r, g, b_c = sp["col"]
            alpha = sp["life"]
            col = (int(r * alpha), int(g * alpha), int(b_c * alpha))
            d.point((int(sp["x"]), int(sp["y"])), fill=col)
            new_sparks.append(sp)
    _ast_sparks = new_sparks

    # 7. Render Ship
    sa = _ast_ship["angle"]
    sx, sy = _ast_ship["x"], _ast_ship["y"]
    nose = (sx + 10 * math.cos(sa), sy + 10 * math.sin(sa))
    left_wing = (sx + 8 * math.cos(sa + 2.5), sy + 8 * math.sin(sa + 2.5))
    right_wing = (sx + 8 * math.cos(sa - 2.5), sy + 8 * math.sin(sa - 2.5))
    d.polygon([nose, left_wing, right_wing], outline=(0, 255, 100), width=1)

    # Render thrust flame if active
    if _ast_ship["thrusting"]:
        flame_tip = (sx - (10 + random.uniform(2, 6)) * math.cos(sa),
                     sy - (10 + random.uniform(2, 6)) * math.sin(sa))
        d.line([left_wing, flame_tip], fill=(220, 140, 20), width=1)
        d.line([right_wing, flame_tip], fill=(220, 140, 20), width=1)

    # 8. Render HUD Header
    try:
        font = ImageFont.load_default()
    except Exception:
        font = None
    if font:
        d.text((45, 16), "COG-ASTEROIDS", fill=(0, 220, 80), font=font)
        d.text((150, 16), f"{_ast_score:05d}", fill=(220, 140, 20), font=font)

    return img


# ── Dispatcher ───────────────────────────────────────────────────────────────

def render_screensaver_frame(anim_name: str, bezel, mask, now: float) -> Image.Image:
    """Render a single frame for the requested screensaver animation name."""
    try:
        if anim_name == "pong":
            return _render_pong_frame(bezel, mask, now)
        elif anim_name == "canticle_rain":
            return _render_canticle_rain_frame(bezel, mask, now)
        elif anim_name == "starfield":
            return _render_starfield_frame(bezel, mask, now)
        elif anim_name == "oscilloscope":
            return _render_oscilloscope_frame(bezel, mask, now)
        elif anim_name == "game_of_life":
            return _render_game_of_life_frame(bezel, mask, now)
        elif anim_name == "radar":
            return _render_radar_frame(bezel, mask, now)
        elif anim_name == "warp_core":
            return _render_warp_core_frame(bezel, mask, now)
        elif anim_name == "circuit_maze":
            return _render_circuit_maze_frame(bezel, mask, now)
        elif anim_name == "double_helix":
            return _render_double_helix_frame(bezel, mask, now)
        elif anim_name == "spinning_rings":
            return _render_spinning_rings_frame(bezel, mask, now)
        elif anim_name == "wireframe_cube":
            return _render_wireframe_cube_frame(bezel, mask, now)
        elif anim_name == "bouncing_cog":
            return _render_bouncing_cog_frame(bezel, mask, now)
        elif anim_name == "fractal_tree":
            return _render_fractal_tree_frame(bezel, mask, now)
        elif anim_name == "hud_status":
            return _render_hud_status_frame(bezel, mask, now)
        elif anim_name == "orbitals":
            return _render_orbitals_frame(bezel, mask, now)
        elif anim_name == "spectrum_bars":
            return _render_spectrum_bars_frame(bezel, mask, now)
        elif anim_name == "plasma":
            return _render_plasma_frame(bezel, mask, now)
        elif anim_name == "lissajous":
            return _render_lissajous_frame(bezel, mask, now)
        elif anim_name == "voronoi":
            return _render_voronoi_frame(bezel, mask, now)
        elif anim_name == "data_stream":
            return _render_data_stream_frame(bezel, mask, now)
        elif anim_name == "mandala":
            return _render_mandala_frame(bezel, mask, now)
        elif anim_name == "rune_wheel":
            return _render_rune_wheel_frame(bezel, mask, now)
        elif anim_name == "glitch":
            return _render_glitch_frame(bezel, mask, now)
        elif anim_name == "dna_helix":
            return _render_dna_helix_frame(bezel, mask, now)
        elif anim_name == "neural_net":
            return _render_neural_net_frame(bezel, mask, now)
        elif anim_name == "gravity_well":
            return _render_gravity_well_frame(bezel, mask, now)
        elif anim_name == "void_shield":
            return _render_void_shield_frame(bezel, mask, now)
        elif anim_name == "hex_grid":
            return _render_hex_grid_frame(bezel, mask, now)
        elif anim_name == "kaleidoscope":
            return _render_kaleidoscope_frame(bezel, mask, now)
        elif anim_name == "particle_burst":
            return _render_particle_burst_frame(bezel, mask, now)
        elif anim_name == "asteroids":
            return _render_asteroids_frame(bezel, mask, now)
        else:
            return _render_starfield_frame(bezel, mask, now)
    except Exception as e:
        return _render_starfield_frame(bezel, mask, now)
