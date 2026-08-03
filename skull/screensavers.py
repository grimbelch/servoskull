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
    "void_shield", "hex_grid", "kaleidoscope", "particle_burst", "asteroids", "battlezone", "trench_run", "vector_dungeon"
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
        elif anim_name == "battlezone":
            return _render_battlezone_frame(bezel, mask, now)
        elif anim_name == "trench_run":
            return _render_trench_run_frame(bezel, mask, now)
        elif anim_name == "vector_dungeon":
            return _render_vector_dungeon_frame(bezel, mask, now)
        else:
            return _render_starfield_frame(bezel, mask, now)
    except Exception as e:
        return _render_starfield_frame(bezel, mask, now)


# Vector Dungeon State
_dng_map = []
_dng_px = 1.5
_dng_py = 1.5
_dng_dir_idx = 0 # 0:N, 1:E, 2:S, 3:W
_dng_heading = 0.0
_dng_step_start_x = 1.5
_dng_step_start_y = 1.5
_dng_step_target_x = 1.5
_dng_step_target_y = 1.5
_dng_step_t = 1.0
_dng_turn_start_h = 0.0
_dng_turn_target_h = 0.0
_dng_turn_t = 1.0
_dng_monster = None
_dng_sparks = []
_dng_score = 0
_dng_last_update = 0.0

def _init_vector_dungeon():
    global _dng_map, _dng_px, _dng_py, _dng_dir_idx, _dng_heading, _dng_step_start_x, _dng_step_start_y, _dng_step_target_x, _dng_step_target_y, _dng_step_t, _dng_turn_start_h, _dng_turn_target_h, _dng_turn_t, _dng_monster, _dng_sparks, _dng_score, _dng_last_update
    _dng_map = [
        [1,1,1,1,1,1,1,1,1,1,1,1],
        [1,0,0,0,1,0,0,0,0,0,0,1],
        [1,0,1,0,1,0,1,1,1,1,0,1],
        [1,0,1,0,0,0,0,0,0,1,0,1],
        [1,0,1,1,1,1,0,1,0,1,0,1],
        [1,0,0,0,0,1,0,1,0,0,0,1],
        [1,1,1,1,0,1,0,1,1,1,0,1],
        [1,0,0,0,0,0,0,0,0,1,0,1],
        [1,0,1,1,1,1,1,1,0,1,0,1],
        [1,0,0,0,0,0,0,1,0,0,0,1],
        [1,0,1,1,1,1,0,0,0,1,0,1],
        [1,1,1,1,1,1,1,1,1,1,1,1]
    ]
    _dng_px = 1.5
    _dng_py = 1.5
    _dng_dir_idx = 0
    _dng_heading = 0.0
    _dng_step_start_x = 1.5
    _dng_step_start_y = 1.5
    _dng_step_target_x = 1.5
    _dng_step_target_y = 1.5
    _dng_step_t = 1.0
    _dng_turn_start_h = 0.0
    _dng_turn_target_h = 0.0
    _dng_turn_t = 1.0
    _dng_monster = None
    _dng_sparks = []
    _dng_score = 0
    _dng_last_update = 0.0


def _render_vector_dungeon_frame(bezel, mask, now):
    """80s Retro 3D Wireframe Dungeon Crawler (Wizardry / Bard's Tale style)."""
    global _dng_map, _dng_px, _dng_py, _dng_dir_idx, _dng_heading, _dng_step_t, _dng_turn_t, _dng_turn_start_h, _dng_turn_target_h, _dng_step_start_x, _dng_step_start_y, _dng_step_target_x, _dng_step_target_y, _dng_monster, _dng_sparks, _dng_score, _dng_last_update

    if not _dng_map:
        _init_vector_dungeon()

    img = Image.new("RGB", (240, 240), (0, 8, 3))
    d = ImageDraw.Draw(img)

    DIRS = [(0, 1), (1, 0), (0, -1), (-1, 0)]  # 0:N, 1:E, 2:S, 3:W
    DIRS_L = [(-1, 0), (0, 1), (1, 0), (0, -1)] # Left offsets
    DIRS_R = [(1, 0), (0, -1), (-1, 0), (0, 1)] # Right offsets

    dt = 0.05
    if _dng_last_update == 0.0:
        _dng_last_update = now
    else:
        dt = max(0.01, min(0.1, now - _dng_last_update))
        _dng_last_update = now

    # 1. Update Navigation & Combat State
    if _dng_monster is not None:
        _dng_monster["timer"] += dt * 2.5
        if _dng_monster["timer"] >= 1.0:
            _dng_score += 2500
            mx, my = _dng_monster["sx"], _dng_monster["sy"]
            for _ in range(25):
                a = random.uniform(0, 2 * math.pi)
                spd = random.uniform(2.0, 6.0)
                _dng_sparks.append({"x": mx, "y": my, "vx": math.cos(a)*spd, "vy": math.sin(a)*spd, "life": 1.0})
            _dng_monster = None

    elif _dng_turn_t < 1.0:
        _dng_turn_t = min(1.0, _dng_turn_t + dt * 2.5)

    elif _dng_step_t < 1.0:
        _dng_step_t = min(1.0, _dng_step_t + dt * 2.5)
        _dng_px = _dng_step_start_x + (_dng_step_target_x - _dng_step_start_x) * _dng_step_t
        _dng_py = _dng_step_start_y + (_dng_step_target_y - _dng_step_start_y) * _dng_step_t

        if _dng_step_t >= 1.0:
            if random.random() < 0.28:
                m_type = random.choice([0, 1, 2])
                _dng_monster = {"type": m_type, "depth": 2.0, "timer": 0.0, "sx": 120, "sy": 120}

    else:
        cur_x = int(_dng_px)
        cur_y = int(_dng_py)
        dx, dy = DIRS[_dng_dir_idx]
        nx, ny = cur_x + dx, cur_y + dy

        if 0 <= nx < 12 and 0 <= ny < 12 and _dng_map[ny][nx] == 0 and random.random() > 0.22:
            _dng_step_start_x = _dng_px
            _dng_step_start_y = _dng_py
            _dng_step_target_x = float(nx) + 0.5
            _dng_step_target_y = float(ny) + 0.5
            _dng_step_t = 0.0
        else:
            valid_dirs = []
            for d_idx in range(4):
                tx = cur_x + DIRS[d_idx][0]
                ty = cur_y + DIRS[d_idx][1]
                if 0 <= tx < 12 and 0 <= ty < 12 and _dng_map[ty][tx] == 0:
                    valid_dirs.append(d_idx)
            if valid_dirs:
                back_idx = (_dng_dir_idx + 2) % 4
                if len(valid_dirs) > 1 and back_idx in valid_dirs:
                    valid_dirs.remove(back_idx)
                next_dir_idx = random.choice(valid_dirs)
                _dng_turn_start_h = float(_dng_dir_idx)
                _dng_turn_target_h = float(next_dir_idx)
                _dng_dir_idx = next_dir_idx
                _dng_turn_t = 0.0

    # 2. Render First-Person 3D Vector Corridor Slices
    DEPTH_BOXES = [
        (15,  225, 15,  225),  # Depth 0 (Near / Eye frame)
        (55,  185, 55,  185),  # Depth 1
        (82,  158, 82,  158),  # Depth 2
        (98,  142, 98,  142),  # Depth 3
        (108, 132, 108, 132)   # Depth 4 (Far end)
    ]

    pan_x = 0.0
    if _dng_turn_t < 1.0:
        pan_dir = _dng_turn_target_h - _dng_turn_start_h
        if pan_dir == 3: pan_dir = -1
        elif pan_dir == -3: pan_dir = 1
        pan_x = (1.0 - _dng_turn_t) * pan_dir * -50.0

    cur_x = int(_dng_px)
    cur_y = int(_dng_py)
    fwd_dx, fwd_dy = DIRS[_dng_dir_idx]
    left_dx, left_dy = DIRS_L[_dng_dir_idx]
    right_dx, right_dy = DIRS_R[_dng_dir_idx]

    for depth in range(4, 0, -1):
        xl_n0, xr_n0, yt_n0, yb_n0 = DEPTH_BOXES[depth - 1]
        xl_f0, xr_f0, yt_f0, yb_f0 = DEPTH_BOXES[depth]

        xl_n = int(xl_n0 + pan_x)
        xr_n = int(xr_n0 + pan_x)
        yt_n = yt_n0
        yb_n = yb_n0

        xl_f = int(xl_f0 + pan_x)
        xr_f = int(xr_f0 + pan_x)
        yt_f = yt_f0
        yb_f = yb_f0

        cell_x = cur_x + fwd_dx * depth
        cell_y = cur_y + fwd_dy * depth

        cell_is_wall = not (0 <= cell_x < 12 and 0 <= cell_y < 12) or _dng_map[cell_y][cell_x] == 1

        if cell_is_wall:
            d.rectangle([xl_f, yt_f, xr_f, yb_f], fill=(0, 8, 3), outline=(0, 220, 80), width=1)
            pad_w = max(2, (xr_f - xl_f) // 4)
            pad_h = max(2, (yb_f - yt_f) // 4)
            d.rectangle([xl_f + pad_w, yt_f + pad_h, xr_f - pad_w, yb_f - pad_h], outline=(0, 160, 60), width=1)
            d.line([(xl_f, (yt_f + yb_f)//2), (xr_f, (yt_f + yb_f)//2)], fill=(0, 140, 50), width=1)
            continue

        lx = cell_x + left_dx
        ly = cell_y + left_dy
        left_is_wall = not (0 <= lx < 12 and 0 <= ly < 12) or _dng_map[ly][lx] == 1

        if left_is_wall:
            d.polygon([(xl_n, yt_n), (xl_f, yt_f), (xl_f, yb_f), (xl_n, yb_n)], fill=(0, 8, 3), outline=(0, 220, 80))
            d.line([(xl_n, yt_n), (xl_n, yb_n)], fill=(0, 255, 100), width=1)
            d.line([(xl_f, yt_f), (xl_f, yb_f)], fill=(0, 255, 100), width=1)
        else:
            d.line([(xl_n, yt_n), (xl_f, yt_f)], fill=(0, 220, 80), width=1)
            d.line([(xl_n, yb_n), (xl_f, yb_f)], fill=(0, 220, 80), width=1)
            d.line([(0, yt_f), (xl_f, yt_f)], fill=(0, 160, 50), width=1)
            d.line([(0, yb_f), (xl_f, yb_f)], fill=(0, 160, 50), width=1)

        rx = cell_x + right_dx
        ry = cell_y + right_dy
        right_is_wall = not (0 <= rx < 12 and 0 <= ry < 12) or _dng_map[ry][rx] == 1

        if right_is_wall:
            d.polygon([(xr_f, yt_f), (xr_n, yt_n), (xr_n, yb_n), (xr_f, yb_f)], fill=(0, 8, 3), outline=(0, 220, 80))
            d.line([(xr_n, yt_n), (xr_n, yb_n)], fill=(0, 255, 100), width=1)
            d.line([(xr_f, yt_f), (xr_f, yb_f)], fill=(0, 255, 100), width=1)
        else:
            d.line([(xr_n, yt_n), (xr_f, yt_f)], fill=(0, 220, 80), width=1)
            d.line([(xr_n, yb_n), (xr_f, yb_f)], fill=(0, 220, 80), width=1)
            d.line([(xr_f, yt_f), (240, yt_f)], fill=(0, 160, 50), width=1)
            d.line([(xr_f, yb_f), (240, yb_f)], fill=(0, 160, 50), width=1)

        d.line([(xl_n, yt_n), (xr_n, yt_n)], fill=(0, 200, 70), width=1)
        d.line([(xl_n, yb_n), (xr_n, yb_n)], fill=(0, 200, 70), width=1)

    # 4. Render 3D Vector Monster Encounter
    if _dng_monster is not None:
        m_type = _dng_monster["type"]
        timer = _dng_monster["timer"]
        md = _dng_monster["depth"]
        m_scale = 140.0 / md
        mc_x, mc_y = 120, 120

        col_m = (220, 140, 20) if timer < 0.5 else (220, 30, 30)

        if m_type == 0:
            r_orb = int(22 * m_scale)
            d.ellipse([mc_x - r_orb, mc_y - r_orb, mc_x + r_orb, mc_y + r_orb], outline=col_m, width=2)
            d.ellipse([mc_x - r_orb//2, mc_y - r_orb//2, mc_x + r_orb//2, mc_y + r_orb//2], outline=(0, 255, 100), width=1)
            for i in range(8):
                ang = i * (math.pi / 4)
                ex = int(mc_x + (r_orb + 12 * m_scale) * math.cos(ang))
                ey = int(mc_y + (r_orb + 12 * m_scale) * math.sin(ang))
                d.line([(mc_x + r_orb * math.cos(ang), mc_y + r_orb * math.sin(ang)), (ex, ey)], fill=col_m, width=1)
                d.ellipse([ex - 2, ey - 2, ex + 2, ey + 2], fill=(220, 30, 30))

        elif m_type == 1:
            w_body = int(24 * m_scale)
            h_body = int(32 * m_scale)
            d.polygon([(mc_x, mc_y - h_body), (mc_x - 10, mc_y - h_body + 10), (mc_x + 10, mc_y - h_body + 10)], outline=col_m)
            d.line([(mc_x - 8, mc_y - h_body + 5), (mc_x - 16, mc_y - h_body - 8)], fill=col_m, width=2)
            d.line([(mc_x + 8, mc_y - h_body + 5), (mc_x + 16, mc_y - h_body - 8)], fill=col_m, width=2)
            d.polygon([(mc_x - 10, mc_y - h_body + 10), (mc_x - w_body - 15, mc_y - 15), (mc_x - 10, mc_y + 10)], outline=col_m)
            d.polygon([(mc_x + 10, mc_y - h_body + 10), (mc_x + w_body + 15, mc_y - 15), (mc_x + 10, mc_y + 10)], outline=col_m)

        else:
            r_sk = int(18 * m_scale)
            d.ellipse([mc_x - r_sk, mc_y - r_sk - 8, mc_x + r_sk, mc_y + r_sk - 8], outline=col_m, width=2)
            d.ellipse([mc_x - 10, mc_y - 12, mc_x - 3, mc_y - 5], fill=(220, 30, 30))
            d.ellipse([mc_x + 3, mc_y - 12, mc_x + 10, mc_y - 5], fill=(220, 30, 30))
            for ry in range(mc_y + 5, mc_y + 35, 7):
                d.line([(mc_x - 14, ry), (mc_x + 14, ry)], fill=col_m, width=1)

        if timer >= 0.5:
            d.line([(120, 240), (mc_x, mc_y)], fill=(0, 255, 120), width=3)
            d.ellipse([mc_x - 15, mc_y - 15, mc_x + 15, mc_y + 15], outline=(220, 140, 20), width=2)

    # 5. Render Sparks / Explosions
    new_sparks = []
    for sp in _dng_sparks:
        sp["x"] += sp["vx"]
        sp["y"] += sp["vy"]
        sp["life"] -= 0.06
        if sp["life"] > 0:
            alpha = sp["life"]
            d.point((int(sp["x"]), int(sp["y"])), fill=(0, int(230*alpha), int(80*alpha)))
            new_sparks.append(sp)
    _dng_sparks = new_sparks

    # 6. Render HUD Overlay & Minimap
    try:
        font = ImageFont.load_default()
    except Exception:
        font = None

    dirs_lbl = ["NORTH", "EAST", "SOUTH", "WEST"]
    cur_x_lbl = int(_dng_px)
    cur_y_lbl = int(_dng_py)

    if font:
        d.text((15, 16), "COG-DUNGEON", fill=(0, 220, 80), font=font)
        d.text((155, 16), f"POS:({cur_x_lbl:02d},{cur_y_lbl:02d})", fill=(220, 140, 20), font=font)
        d.text((15, 215), f"DIR: {dirs_lbl[_dng_dir_idx]}", fill=(0, 180, 60), font=font)
        d.text((150, 215), f"SCORE: {_dng_score:05d}", fill=(220, 140, 20), font=font)

        if _dng_monster is not None:
            d.text((65, 34), "[ HOSTILE ENCOUNTER ]", fill=(220, 30, 30), font=font)

    return img


# Trench Run Arcade State
_tr_dist = 0.0
_tr_barriers = []
_tr_turrets = []
_tr_bolts = []
_tr_torpedoes = []
_tr_sparks = []
_tr_score = 0
_tr_last_shot = 0.0
_tr_exhaust_port_mode = False
_tr_exhaust_port_z = 0.0
_tr_hit_flash = 0.0

def _init_trench_run():
    global _tr_dist, _tr_barriers, _tr_turrets, _tr_bolts, _tr_torpedoes, _tr_sparks, _tr_score, _tr_last_shot, _tr_exhaust_port_mode, _tr_exhaust_port_z, _tr_hit_flash
    _tr_dist = 2000.0
    _tr_barriers = []
    for i in range(5):
        _tr_barriers.append({
            "z": 100.0 + i * 150.0,
            "type": random.choice(["top", "bottom", "left", "right", "center_cross"])
        })
    _tr_turrets = []
    for i in range(8):
        side = random.choice([-1, 1])
        _tr_turrets.append({
            "z": 80.0 + i * 90.0,
            "side": side,
            "y": random.uniform(-30, 30)
        })
    _tr_bolts = []
    _tr_torpedoes = []
    _tr_sparks = []
    _tr_score = 0
    _tr_last_shot = 0.0
    _tr_exhaust_port_mode = False
    _tr_exhaust_port_z = 0.0
    _tr_hit_flash = 0.0


def _render_trench_run_frame(bezel, mask, now):
    """Vector Arcade Star Wars Trench Run Simulator – Adeptus Mechanicus edition."""
    global _tr_dist, _tr_barriers, _tr_turrets, _tr_bolts, _tr_torpedoes, _tr_sparks, _tr_score, _tr_last_shot, _tr_exhaust_port_mode, _tr_exhaust_port_z, _tr_hit_flash

    if not _tr_barriers or not _tr_turrets:
        _init_trench_run()

    img = Image.new("RGB", (240, 240), (0, 8, 3))
    d = ImageDraw.Draw(img)

    # 1. Update distance & speed
    speed = 4.5
    _tr_dist = max(0.0, _tr_dist - speed * 0.4)

    if _tr_dist <= 150.0 and not _tr_exhaust_port_mode:
        _tr_exhaust_port_mode = True
        _tr_exhaust_port_z = 350.0

    sway_x = math.sin(now * 2.0) * 8.0
    sway_y = math.cos(now * 1.5) * 6.0

    def proj(x, y, z):
        if z <= 2.0:
            return None
        scale = 160.0 / z
        sx = 120 + (x + sway_x) * scale
        sy = 120 - (y + sway_y) * scale
        return (sx, sy)

    # 2. Draw Vector Trench Framework
    wall_x_left, wall_x_right = -60.0, 60.0
    floor_y, top_y = -45.0, 45.0

    z_near, z_far = 10.0, 380.0
    p_nlf = proj(wall_x_left, floor_y, z_near)
    p_flf = proj(wall_x_left, floor_y, z_far)
    p_nrf = proj(wall_x_right, floor_y, z_near)
    p_frf = proj(wall_x_right, floor_y, z_far)
    p_nlt = proj(wall_x_left, top_y, z_near)
    p_flt = proj(wall_x_left, top_y, z_far)
    p_nrt = proj(wall_x_right, top_y, z_near)
    p_frt = proj(wall_x_right, top_y, z_far)

    if p_nlf and p_flf: d.line([p_nlf, p_flf], fill=(0, 200, 70), width=1)
    if p_nrf and p_frf: d.line([p_nrf, p_frf], fill=(0, 200, 70), width=1)
    if p_nlt and p_flt: d.line([p_nlt, p_flt], fill=(0, 200, 70), width=1)
    if p_nrt and p_frt: d.line([p_nrt, p_frt], fill=(0, 200, 70), width=1)

    z_offset = (_tr_dist * 5.0) % 40.0
    for rz in range(15, 380, 40):
        z_curr = rz - z_offset
        if z_curr > 8.0:
            c1 = proj(wall_x_left, floor_y, z_curr)
            c2 = proj(wall_x_right, floor_y, z_curr)
            c3 = proj(wall_x_right, top_y, z_curr)
            c4 = proj(wall_x_left, top_y, z_curr)
            if c1 and c2 and c3 and c4:
                d.polygon([c1, c2, c3, c4], outline=(0, 140, 45), width=1)

    # 3. Process & Draw Catwalk Barriers
    for b in _tr_barriers:
        b["z"] -= speed * 1.5
        if b["z"] <= 8.0:
            b["z"] = 400.0
            b["type"] = random.choice(["top", "bottom", "left", "right", "center_cross"])

        bz = b["z"]
        if bz > 8.0:
            c1 = proj(wall_x_left, floor_y, bz)
            c2 = proj(wall_x_right, floor_y, bz)
            c3 = proj(wall_x_right, top_y, bz)
            c4 = proj(wall_x_left, top_y, bz)

            if c1 and c2 and c3 and c4:
                b_type = b["type"]
                col = (220, 140, 20)
                if b_type == "top":
                    cm1 = proj(wall_x_left, 0.0, bz)
                    cm2 = proj(wall_x_right, 0.0, bz)
                    if cm1 and cm2:
                        d.polygon([cm1, cm2, c3, c4], outline=col, width=1)
                elif b_type == "bottom":
                    cm1 = proj(wall_x_left, 0.0, bz)
                    cm2 = proj(wall_x_right, 0.0, bz)
                    if cm1 and cm2:
                        d.polygon([c1, c2, cm2, cm1], outline=col, width=1)
                elif b_type == "left":
                    cm1 = proj(0.0, floor_y, bz)
                    cm2 = proj(0.0, top_y, bz)
                    if cm1 and cm2:
                        d.polygon([c1, cm1, cm2, c4], outline=col, width=1)
                elif b_type == "right":
                    cm1 = proj(0.0, floor_y, bz)
                    cm2 = proj(0.0, top_y, bz)
                    if cm1 and cm2:
                        d.polygon([cm1, c2, c3, cm2], outline=col, width=1)
                else:
                    d.line([c1, c3], fill=col, width=1)
                    d.line([c2, c4], fill=col, width=1)

    # 4. Process & Draw Wall Turrets
    for tur in _tr_turrets:
        tur["z"] -= speed * 1.5
        if tur["z"] <= 8.0:
            tur["z"] = 400.0
            tur["side"] = random.choice([-1, 1])
            tur["y"] = random.uniform(-35, 35)

        tz = tur["z"]
        if tz > 8.0:
            tx = wall_x_left if tur["side"] == -1 else wall_x_right
            ty = tur["y"]
            p_tur = proj(tx, ty, tz)
            if p_tur:
                d.ellipse([p_tur[0]-3, p_tur[1]-3, p_tur[0]+3, p_tur[1]+3], outline=(0, 255, 100))
                if random.random() < 0.03 and (now - _tr_last_shot > 0.4):
                    _tr_last_shot = now
                    _tr_bolts.append({"x": tx, "y": ty, "z": tz, "speed": 14.0})

    # 5. Process Turret Bolts
    new_bolts = []
    for blt in _tr_bolts:
        blt["z"] -= blt["speed"]
        if blt["z"] > 6.0:
            p_b = proj(blt["x"], blt["y"], blt["z"])
            if p_b and 0 <= p_b[0] <= 240 and 0 <= p_b[1] <= 240:
                d.ellipse([p_b[0]-2, p_b[1]-2, p_b[0]+2, p_b[1]+2], fill=(220, 30, 30))
                new_bolts.append(blt)
    _tr_bolts = new_bolts

    # 6. Thermal Exhaust Port Mode & Torpedoes
    if _tr_exhaust_port_mode:
        _tr_exhaust_port_z -= speed * 1.2
        ep_z = _tr_exhaust_port_z

        if ep_z > 15.0:
            p_ep = proj(0.0, floor_y, ep_z)
            if p_ep:
                r_ep = max(4, int(450.0 / ep_z))
                d.ellipse([p_ep[0]-r_ep, p_ep[1]-r_ep, p_ep[0]+r_ep, p_ep[1]+r_ep], outline=(220, 140, 20), width=2)
                d.ellipse([p_ep[0]-r_ep//2, p_ep[1]-r_ep//2, p_ep[0]+r_ep//2, p_ep[1]+r_ep//2], outline=(0, 255, 100), width=1)

                if ep_z < 180.0 and len(_tr_torpedoes) == 0:
                    _tr_torpedoes.append({"x": -20.0, "y": -20.0, "z": 20.0, "tz": ep_z})
                    _tr_torpedoes.append({"x": 20.0, "y": -20.0, "z": 20.0, "tz": ep_z})

        new_torp = []
        for tp in _tr_torpedoes:
            tp["z"] += 12.0
            p_tp = proj(tp["x"], tp["y"], tp["z"])
            if p_tp:
                d.ellipse([p_tp[0]-3, p_tp[1]-3, p_tp[0]+3, p_tp[1]+3], fill=(0, 255, 255))
            if tp["z"] >= ep_z:
                _tr_score += 10000
                _tr_hit_flash = 1.0
                for _ in range(30):
                    a = random.uniform(0, 2 * math.pi)
                    spd = random.uniform(2.0, 7.0)
                    _tr_sparks.append({"x": 120, "y": 140, "vx": math.cos(a)*spd, "vy": math.sin(a)*spd, "life": 1.0})
            else:
                new_torp.append(tp)
        _tr_torpedoes = new_torp

        if ep_z <= 15.0:
            _tr_dist = 2000.0
            _tr_exhaust_port_mode = False

    new_sparks = []
    for sp in _tr_sparks:
        sp["x"] += sp["vx"]
        sp["y"] += sp["vy"]
        sp["life"] -= 0.04
        if sp["life"] > 0:
            alpha = sp["life"]
            d.point((int(sp["x"]), int(sp["y"])), fill=(0, int(255*alpha), int(200*alpha)))
            new_sparks.append(sp)
    _tr_sparks = new_sparks

    # 7. X-Wing Targeting Sight & Cockpit HUD
    ret_x, ret_y = 120, 120
    d.line([(ret_x - 15, ret_y), (ret_x - 5, ret_y)], fill=(220, 140, 20), width=1)
    d.line([(ret_x + 5, ret_y), (ret_x + 15, ret_y)], fill=(220, 140, 20), width=1)
    d.line([(ret_x, ret_y - 15), (ret_x, ret_y - 5)], fill=(220, 140, 20), width=1)
    d.line([(ret_x, ret_y + 5), (ret_x, ret_y + 15)], fill=(220, 140, 20), width=1)
    d.ellipse([ret_x - 8, ret_y - 8, ret_x + 8, ret_y + 8], outline=(0, 255, 100), width=1)

    if random.random() < 0.3:
        d.line([(10, 220), (115, 125)], fill=(220, 30, 30), width=2)
        d.line([(230, 220), (125, 125)], fill=(220, 30, 30), width=2)

    # 8. Render HUD Header
    try:
        font = ImageFont.load_default()
    except Exception:
        font = None

    if font:
        d.text((15, 16), "COG-TRENCH-RUN", fill=(0, 220, 80), font=font)
        d.text((150, 16), f"DIST: {int(_tr_dist):04d}m", fill=(220, 140, 20), font=font)
        if _tr_exhaust_port_mode:
            d.text((68, 34), "[ EXHAUST PORT LOCK ]", fill=(220, 30, 30), font=font)

    if _tr_hit_flash > 0:
        _tr_hit_flash = max(0.0, _tr_hit_flash - 0.1)
        overlay = Image.new("RGB", (240, 240), (0, 255, 180))
        img = Image.blend(img, overlay, _tr_hit_flash * 0.4)

    return img


# Battlezone Arcade State
_bz_player = None
_bz_tanks = []
_bz_shells = []
_bz_explosions = []
_bz_mountains = []
_bz_score = 0
_bz_last_shot = 0.0

def _init_battlezone():
    global _bz_player, _bz_tanks, _bz_shells, _bz_explosions, _bz_mountains, _bz_score, _bz_last_shot
    _bz_player = {"x": 0.0, "z": 0.0, "heading": 0.0, "speed": 1.4}
    _bz_tanks = []
    for _ in range(3):
        angle = random.uniform(0, math.pi * 2)
        dist = random.uniform(90, 220)
        _bz_tanks.append({
            "x": dist * math.sin(angle),
            "z": dist * math.cos(angle),
            "heading": random.uniform(0, math.pi * 2),
            "speed": random.uniform(0.4, 0.9),
            "turret_angle": random.uniform(0, math.pi * 2)
        })
    _bz_shells = []
    _bz_explosions = []
    _bz_score = 0
    _bz_last_shot = 0.0

    _bz_mountains = []
    num_peaks = 36
    for i in range(num_peaks):
        a = i * (2 * math.pi / num_peaks)
        h = random.uniform(12, 32) if (i % 3 == 0) else random.uniform(2, 10)
        _bz_mountains.append((a, h))


def _render_battlezone_frame(bezel, mask, now):
    """Vector Arcade Battlezone Periscope Simulator – Adeptus Mechanicus edition."""
    global _bz_player, _bz_tanks, _bz_shells, _bz_explosions, _bz_score, _bz_last_shot, _bz_mountains

    if _bz_player is None or not _bz_mountains:
        _init_battlezone()

    img = Image.new("RGB", (240, 240), (0, 8, 3))
    d = ImageDraw.Draw(img)

    # 1. Update Player position & orientation
    _bz_player["heading"] += math.sin(now * 0.3) * 0.015
    _bz_player["x"] += math.sin(_bz_player["heading"]) * _bz_player["speed"]
    _bz_player["z"] += math.cos(_bz_player["heading"]) * _bz_player["speed"]

    # 2. Draw Distant Vector Mountain Horizon
    horizon_y = 120
    d.line([(0, horizon_y), (240, horizon_y)], fill=(0, 70, 25), width=1)

    m_pts = []
    head = _bz_player["heading"]
    for a, h in _bz_mountains:
        rel_a = (a - head + math.pi) % (2 * math.pi) - math.pi
        if abs(rel_a) < math.pi / 2:
            sx = int(120 + math.tan(rel_a) * 160)
            sy = int(horizon_y - h)
            m_pts.append((sx, sy))

    m_pts.sort(key=lambda p: p[0])
    for i in range(len(m_pts) - 1):
        if 0 <= m_pts[i][0] <= 240 or 0 <= m_pts[i+1][0] <= 240:
            d.line([m_pts[i], m_pts[i+1]], fill=(0, 160, 50), width=1)

    # 3. Ground Perspective Grid Lines
    grid_offset = (_bz_player["z"] * 0.1) % 20
    for gz in range(20, 200, 25):
        z_eff = gz - grid_offset
        if z_eff > 5:
            sy = int(horizon_y + 1600.0 / z_eff)
            if horizon_y < sy < 240:
                d.line([(0, sy), (240, sy)], fill=(0, 40, 15), width=1)

    for gx in [-120, -60, 0, 60, 120]:
        rel_x = gx - (_bz_player["x"] * 0.1 % 60)
        d.line([(120 + rel_x * 0.2, horizon_y), (120 + rel_x * 1.5, 240)], fill=(0, 35, 12), width=1)

    # 4. Process & Project 3D Wireframe Enemy Tanks
    target_in_reticle = False

    for tank in _bz_tanks:
        tank["x"] += math.sin(tank["heading"]) * tank["speed"]
        tank["z"] += math.cos(tank["heading"]) * tank["speed"]

        dx = tank["x"] - _bz_player["x"]
        dz = tank["z"] - _bz_player["z"]

        rx = dx * math.cos(_bz_player["heading"]) - dz * math.sin(_bz_player["heading"])
        rz = dx * math.sin(_bz_player["heading"]) + dz * math.cos(_bz_player["heading"])

        if rz > 5.0:
            scale = 160.0 / rz
            sx = 120 + rx * scale
            sy = horizon_y + 15 * scale

            tw = max(4, int(18 * scale))
            th = max(3, int(12 * scale))

            if -40 <= sx <= 280:
                hull_pts = [
                    (sx - tw, sy), (sx + tw, sy),
                    (sx + tw * 0.8, sy - th), (sx - tw * 0.8, sy - th)
                ]
                d.polygon(hull_pts, outline=(0, 220, 80), width=1)

                turret_y = sy - th
                barrel_x = sx + math.sin(tank["turret_angle"] - _bz_player["heading"]) * (tw * 0.8)
                d.rectangle([sx - tw * 0.4, turret_y - th * 0.5, sx + tw * 0.4, turret_y], outline=(0, 255, 100))
                d.line([(sx, turret_y - th * 0.25), (barrel_x, turret_y - th * 0.7)], fill=(0, 255, 100), width=2)

                if abs(sx - 120) < 25:
                    target_in_reticle = True

    # 5. Cannon Shells & Explosions
    if (target_in_reticle or random.random() < 0.04) and (now - _bz_last_shot > 0.8):
        _bz_last_shot = now
        _bz_shells.append({"x": 0.0, "z": 10.0, "speed": 12.0})

    new_shells = []
    for sh in _bz_shells:
        sh["z"] += sh["speed"]
        scale = 160.0 / sh["z"]
        sx = 120 + sh["x"] * scale
        sy = horizon_y + 10 * scale

        hit = False
        for tank in list(_bz_tanks):
            dx = tank["x"] - _bz_player["x"]
            dz = tank["z"] - _bz_player["z"]
            rx = dx * math.cos(_bz_player["heading"]) - dz * math.sin(_bz_player["heading"])
            rz = dx * math.sin(_bz_player["heading"]) + dz * math.cos(_bz_player["heading"])
            if rz > 5.0 and math.hypot(sh["z"] - rz, rx) < 18.0:
                hit = True
                _bz_score += 1500
                for _ in range(random.randint(10, 18)):
                    a = random.uniform(0, 2 * math.pi)
                    spd = random.uniform(2.0, 6.0)
                    _bz_explosions.append({
                        "sx": sx, "sy": sy,
                        "vx": math.cos(a) * spd, "vy": math.sin(a) * spd,
                        "life": 1.0
                    })
                _bz_tanks.remove(tank)
                ang = random.uniform(0, math.pi * 2)
                d_new = random.uniform(150, 260)
                _bz_tanks.append({
                    "x": _bz_player["x"] + d_new * math.sin(ang),
                    "z": _bz_player["z"] + d_new * math.cos(ang),
                    "heading": random.uniform(0, math.pi * 2),
                    "speed": random.uniform(0.4, 0.9),
                    "turret_angle": random.uniform(0, math.pi * 2)
                })
                break

        if not hit and sh["z"] < 250.0:
            d.ellipse([sx - 2, sy - 2, sx + 2, sy + 2], fill=(220, 140, 20))
            new_shells.append(sh)

    _bz_shells = new_shells

    new_exp = []
    for exp in _bz_explosions:
        exp["sx"] += exp["vx"]
        exp["sy"] += exp["vy"]
        exp["life"] -= 0.05
        if exp["life"] > 0:
            alpha = exp["life"]
            col = (int(220 * alpha), int(140 * alpha), 0)
            d.ellipse([exp["sx"] - 2, exp["sy"] - 2, exp["sx"] + 2, exp["sy"] + 2], fill=col)
            new_exp.append(exp)
    _bz_explosions = new_exp

    # 6. Radar Scope & Periscope Reticle
    d.ellipse([95, 8, 145, 58], outline=(0, 180, 60), width=1)
    d.ellipse([115, 28, 125, 38], outline=(0, 80, 25), width=1)
    d.line([(120, 8), (120, 58)], fill=(0, 60, 20), width=1)
    d.line([(95, 33), (145, 33)], fill=(0, 60, 20), width=1)
    for tank in _bz_tanks:
        dx = tank["x"] - _bz_player["x"]
        dz = tank["z"] - _bz_player["z"]
        rx = dx * math.cos(_bz_player["heading"]) - dz * math.sin(_bz_player["heading"])
        rz = dx * math.sin(_bz_player["heading"]) + dz * math.cos(_bz_player["heading"])
        blip_x = 120 + max(-20, min(20, rx * 0.15))
        blip_y = 33 - max(-20, min(20, rz * 0.15))
        d.ellipse([blip_x - 1, blip_y - 1, blip_x + 1, blip_y + 1], fill=(0, 255, 100))

    d.line([(110, 120), (130, 120)], fill=(0, 255, 100), width=1)
    d.line([(120, 110), (120, 130)], fill=(0, 255, 100), width=1)
    d.rectangle([105, 105, 135, 135], outline=(0, 180, 60) if not target_in_reticle else (220, 140, 20), width=1)

    try:
        font = ImageFont.load_default()
    except Exception:
        font = None

    if font:
        d.text((15, 68), "COG-BATTLEZONE", fill=(0, 220, 80), font=font)
        d.text((165, 68), f"{_bz_score:06d}", fill=(220, 140, 20), font=font)
        if target_in_reticle:
            d.text((82, 142), "[ TARGET LOCK ]", fill=(220, 140, 20), font=font)

    return img
