import sys
from pathlib import Path

# Add project root to path
sys.path.append(str(Path(__file__).resolve().parent.parent))

from skull import brain
from skull import display

def test_display_art(query):
    print(f"Testing display_art with query: '{query}'")
    # Setup dummy display state so _available is True for tests
    display._available = True
    
    # Run the brain tool execution directly
    res = brain._execute_display_art(query)
    print(f"Result: {res}")
    
    # Verify that display._custom_image was populated
    if display._showing_custom_image and display._custom_image:
        print(f"Success! Custom image size: {display._custom_image.size}")
        # Save the rendered frame as a diagnostic image
        out_path = Path(__file__).resolve().parent.parent / "scratch" / f"art_{query.replace(' ', '_')}.png"
        
        display._custom_image.save(out_path)
        print(f"Saved diagnostic frame to {out_path}")
    else:
        print("Failure: display custom image state was not updated correctly.")

if __name__ == "__main__":
    test_display_art("Space Marine")
    test_display_art("Necromunda Escher")
