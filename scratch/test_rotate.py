import cv2
import pathlib

def main():
    img_path = pathlib.Path(__file__).parent / "reference_raw.jpg"
    img = cv2.imread(str(img_path))
    
    # 90 degrees clockwise
    cw = cv2.rotate(img, cv2.ROTATE_90_CLOCKWISE)
    cv2.imwrite(str(pathlib.Path(__file__).parent / "test_cw.jpg"), cw)
    
    # 90 degrees counter-clockwise
    ccw = cv2.rotate(img, cv2.ROTATE_90_COUNTERCLOCKWISE)
    cv2.imwrite(str(pathlib.Path(__file__).parent / "test_ccw.jpg"), ccw)
    
    print("Done rotating!")

if __name__ == "__main__":
    main()
