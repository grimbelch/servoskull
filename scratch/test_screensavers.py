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
    
    anims = ["pong", "canticle_rain", "starfield", "oscilloscope", "game_of_life", "radar"]
    
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
            
        # Save output
        output_path = pathlib.Path(__file__).parent / f"test_{anim}.png"
        img.save(output_path)
        print(f"Saved to: {output_path}")

if __name__ == "__main__":
    main()
