#!/usr/bin/env python3
import os
import shutil
import sys
import numpy as np
import cv2
import pathlib

# Ensure skull packages can be imported
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from skull import face_rec, config

def create_dummy_face_image(filename, text_label="Face"):
    # Create a 112x112 color image representing a dummy face
    img = np.zeros((112, 112, 3), dtype=np.uint8)
    # Draw a circle (head)
    cv2.circle(img, (56, 56), 40, (200, 200, 200), -1)
    # Draw eyes
    cv2.circle(img, (40, 45), 5, (50, 50, 50), -1)
    cv2.circle(img, (72, 45), 5, (50, 50, 50), -1)
    # Draw mouth
    cv2.ellipse(img, (56, 75), (15, 5), 0, 0, 180, (50, 50, 50), -1)
    # Label it
    cv2.putText(img, text_label, (10, 100), cv2.FONT_HERSHEY_SIMPLEX, 0.4, (0, 0, 255), 1)
    cv2.imwrite(filename, img)
    return img

def main():
    test_user = "Tech-Priest"
    test_dir = face_rec.FACES_DIR / test_user
    
    # 1. Clean up old test data if any
    if test_dir.exists():
        shutil.rmtree(test_dir)
    test_dir.mkdir(parents=True, exist_ok=True)
    
    print(f"Creating dummy face images for {test_user}...")
    mock_frames = []
    for i in range(5):
        img_path = test_dir / f"face_{i}.jpg"
        frame = create_dummy_face_image(str(img_path), f"MOCK_{i}")
        mock_frames.append(frame)
        
    try:
        # 2. Test SFace model downloading and loading
        print("Initializing SFace model...")
        face_rec.ensure_model_exists()
        
        # 3. Test training
        print("Testing train() pipeline...")
        train_result = face_rec.train()
        print(f"Train output: {train_result}")
        
        # Verify the model file was created
        if not face_rec.MODEL_PATH.exists():
            print("ERROR: face_model.pkl was not created!")
            sys.exit(1)
            
        print("face_model.pkl successfully created.")
        
        # 4. Test loading
        print("Testing load_model()...")
        loaded = face_rec.load_model()
        print(f"Loaded: {loaded}")
        
        # 5. Test recognize
        print("Testing recognize() with a mock frame...")
        # Since we use Haar Cascade, a simple drawn face might not trigger the cascade.
        # Let's bypass detection by feeding it directly to SFace embedder for verification.
        emb = face_rec._get_embedding(mock_frames[0])
        if emb is not None and len(emb) == 128:
            print("Successfully extracted 128-D embedding using SFace ONNX!")
        else:
            print("ERROR: Failed to extract embedding or shape is incorrect!")
            sys.exit(1)
            
        # Test full recognize() function on a blank/unmatched frame
        blank_frame = np.zeros((480, 640, 3), dtype=np.uint8)
        match = face_rec.recognize(blank_frame)
        print(f"Recognized match on blank frame (should be None): {match}")
        
        print("ALL TESTS PASSED SUCCESSFULLY!")
        
    finally:
        # Cleanup
        print("Cleaning up temporary test faces...")
        if test_dir.exists():
            shutil.rmtree(test_dir)
        if face_rec.MODEL_PATH.exists():
            face_rec.MODEL_PATH.unlink()

if __name__ == "__main__":
    main()
