"""
Diagnostic test script to verify rendering geometry and layout of all 6 screensavers.
Saves test frames to scratch/test_<screensaver>.png.
"""

import sys
import pathlib

# Allow import of skull module
sys.path.append(str(pathlib.Path(__file__).parent.parent))

from skull import display

def main():
    print("Testing screensavers rendering...")
    
    # Initialize state variables
    display._pong_ball_x = 110.0
    display._pong_ball_y = 130.0
    display._pong_ball_dx = 2.0
    display._pong_ball_dy = -1.0
    display._pong_paddle_l_y = 125.0
    display._pong_paddle_r_y = 135.0
    display._pong_score_l = 3
    display._pong_score_r = 2
    
    # Generate bezel and mask
    bezel = display._make_bezel()
    mask = display._make_iris_mask()
    
    import time
    now = time.monotonic()
    
    anims = [
        "pong", "canticle_rain", "starfield", "oscilloscope", "game_of_life", "radar",
        "warp_core", "circuit_maze", "double_helix", "spinning_rings", "wireframe_cube",
        "bouncing_cog", "fractal_tree", "hud_status", "orbitals", "spectrum_bars"
    ]
    
    for anim in anims:
        print(f"Rendering: {anim}...")
        display._active_idle_anim = anim
        
        # Initialize
        if anim == "canticle_rain":
            display._init_canticle_rain()
        elif anim == "starfield":
            display._init_starfield()
        elif anim == "game_of_life":
            display._init_game_of_life()
        elif anim == "radar":
            display._init_radar()
        elif anim == "circuit_maze":
            display._init_circuit_maze()
        elif anim == "bouncing_cog":
            display._init_bouncing_cog()
        elif anim == "orbitals":
            display._init_orbitals()
        elif anim == "spectrum_bars":
            display._init_spectrum_bars()
            
        # Render
        if anim == "pong":
            img = display._render_pong_frame(bezel, mask, now)
        elif anim == "canticle_rain":
            img = display._render_canticle_rain_frame(bezel, mask, now)
        elif anim == "starfield":
            img = display._render_starfield_frame(bezel, mask, now)
        elif anim == "oscilloscope":
            img = display._render_oscilloscope_frame(bezel, mask, now)
        elif anim == "game_of_life":
            img = display._render_game_of_life_frame(bezel, mask, now)
        elif anim == "radar":
            img = display._render_radar_frame(bezel, mask, now)
        elif anim == "warp_core":
            img = display._render_warp_core_frame(bezel, mask, now)
        elif anim == "circuit_maze":
            img = display._render_circuit_maze_frame(bezel, mask, now)
        elif anim == "double_helix":
            img = display._render_double_helix_frame(bezel, mask, now)
        elif anim == "spinning_rings":
            img = display._render_spinning_rings_frame(bezel, mask, now)
        elif anim == "wireframe_cube":
            img = display._render_wireframe_cube_frame(bezel, mask, now)
        elif anim == "bouncing_cog":
            img = display._render_bouncing_cog_frame(bezel, mask, now)
        elif anim == "fractal_tree":
            img = display._render_fractal_tree_frame(bezel, mask, now)
        elif anim == "hud_status":
            img = display._render_hud_status_frame(bezel, mask, now)
        elif anim == "orbitals":
            img = display._render_orbitals_frame(bezel, mask, now)
        elif anim == "spectrum_bars":
            img = display._render_spectrum_bars_frame(bezel, mask, now)
            
        # Save output
        output_path = pathlib.Path(__file__).parent / f"test_{anim}.png"
        img.save(output_path)
        print(f"Saved to: {output_path}")

if __name__ == "__main__":
    main()
