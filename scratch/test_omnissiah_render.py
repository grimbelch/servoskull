import sys
import os

# Add parent directory of scratch to sys.path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from skull import display

def test_render():
    print("Initializing test environment on Pi...")
    # Mock parameters
    display._CX = display._CY = 120
    display.W = display.H = 240
    
    # Generate bezel and mask
    bezel = display._make_bezel()
    mask = display._make_iris_mask()
    
    display._omnissiah_start_time = 0.0
    display._omnissiah_duration = 4.0
    
    times_to_test = [0.1, 0.75, 2.0]
    out_dir = os.path.dirname(os.path.abspath(__file__))
    
    for idx, t in enumerate(times_to_test):
        print(f"Rendering frame at t = {t}s...")
        img = display._render_omnissiah_frame(bezel, mask, t)
        
        out_path = os.path.join(out_dir, f"omnissiah_t{idx}.png")
        img.save(out_path)
        print(f"Saved to {out_path}")

if __name__ == "__main__":
    test_render()
