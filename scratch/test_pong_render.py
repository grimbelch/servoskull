"""
Diagnostic test script to verify Pong screensaver rendering geometry and layout.
Saves a test frame of the Pong game to scratch/pong_test.png.
"""

import sys
import pathlib

# Allow import of skull module
sys.path.append(str(pathlib.Path(__file__).parent.parent))

from skull import display

def main():
    print("Testing Pong screensaver rendering...")
    
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
    
    # Render a frame
    import time
    now = time.monotonic()
    img = display._render_pong_frame(bezel, mask, now)
    
    # Save the output image
    output_path = pathlib.Path(__file__).parent / "pong_test.png"
    img.save(output_path)
    print(f"Pong frame successfully saved to: {output_path}")

if __name__ == "__main__":
    main()
