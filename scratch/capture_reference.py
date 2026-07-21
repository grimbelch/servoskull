import sys
import pathlib
import cv2

# Add parent dir to path
sys.path.append(str(pathlib.Path(__file__).parent.parent))

from skull import config

def main():
    print("Initializing camera backend...")
    try:
        from picamera2 import Picamera2
        picam2 = Picamera2()
        picam2.configure(
            picam2.create_preview_configuration(main={"size": (640, 480), "format": "RGB888"})
        )
        picam2.start()
        print("Capturing frame...")
        rgb = picam2.capture_array()
        frame = cv2.cvtColor(rgb, cv2.COLOR_RGB2BGR)
        picam2.stop()
    except ImportError:
        print("picamera2 not available, trying cv2...")
        cap = cv2.VideoCapture(config.CAMERA_DEVICE_INDEX)
        if not cap.isOpened():
            print("Could not open cv2 camera")
            return
        ret, frame = cap.read()
        cap.release()
        if not ret:
            print("Failed to capture via cv2")
            return

    output_path = pathlib.Path(__file__).parent / "reference_raw.jpg"
    cv2.imwrite(str(output_path), frame)
    print(f"Captured successfully! Saved to {output_path}")

if __name__ == "__main__":
    main()
