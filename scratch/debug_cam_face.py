#!/usr/bin/env python3
import os
import sys
import time
import cv2

# Ensure skull packages can be imported
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from skull import camera, face_rec, config

def main():
    print("Initializing camera backend...")
    config.CAMERA_ENABLED = True
    backend = camera._open_backend()
    if backend is None:
        print("ERROR: Camera backend could not be opened!")
        sys.exit(1)
        
    read, close = backend
    try:
        # Wait a moment for camera to auto-exposure
        print("Warming up camera...")
        time.sleep(2.0)
        
        # Create debug directory
        debug_dir = pathlib.Path(config.data_path("faces/debug_faces"))
        debug_dir.mkdir(parents=True, exist_ok=True)
        
        print("Capturing 5 frames...")
        for i in range(5):
            frame = read()
            if frame is None:
                print(f"Frame {i}: Failed to read!")
                continue
                
            print(f"Frame {i} shape: {frame.shape}")
            res = face_rec.detect_face(frame)
            if res:
                rotated_img, rect = res
                print(f"Frame {i}: Face detected at rect {rect}!")
                # Draw rect
                x, y, w, h = rect
                draw_img = rotated_img.copy()
                cv2.rectangle(draw_img, (x, y), (x+w, y+h), (0, 255, 0), 2)
                cv2.imwrite(str(debug_dir / f"frame_{i}_detected.jpg"), draw_img)
            else:
                print(f"Frame {i}: No face detected in any rotation.")
                # Save original frame
                cv2.imwrite(str(debug_dir / f"frame_{i}_raw.jpg"), frame)
                
            time.sleep(1.0)
            
    finally:
        close()
        print("Done. Saved debug frames to faces/debug_faces/")

if __name__ == "__main__":
    import pathlib
    main()
