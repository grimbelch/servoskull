"""
Lightweight biometric face recognition module using OpenCV SFace deep face embeddings.
Keeps biometric profiles stored in USER_DATA_DIR/faces/ and stores embeddings in face_model.pkl.
"""

from __future__ import annotations
import os
import pickle
import pathlib
import numpy as np
import cv2
import requests
from skull import config

# Directories
FACES_DIR = pathlib.Path(config.data_path("faces"))
MODEL_PATH = FACES_DIR / "face_model.pkl"
MODEL_DIR = pathlib.Path(config.data_path("models"))
SFACE_MODEL_PATH = MODEL_DIR / "face_recognition_sface_2021dec.onnx"
SFACE_MODEL_URL = "https://github.com/opencv/opencv_zoo/raw/main/models/face_recognition_sface/face_recognition_sface_2021dec.onnx"

# Load the face detector Cascade
_cascade_path = cv2.data.haarcascades + "haarcascade_frontalface_default.xml"
_face_cascade = cv2.CascadeClassifier(_cascade_path)

# Active trained model cache
_embeddings_db: dict[str, list[np.ndarray]] = {}
_net = None

def ensure_model_exists() -> None:
    """Download SFace ONNX model if not already present."""
    if SFACE_MODEL_PATH.exists():
        return
    MODEL_DIR.mkdir(parents=True, exist_ok=True)
    print(f"[face_rec] Downloading SFace face recognition model from {SFACE_MODEL_URL}...")
    try:
        response = requests.get(SFACE_MODEL_URL, stream=True, timeout=30)
        response.raise_for_status()
        with SFACE_MODEL_PATH.open("wb") as f:
            for chunk in response.iter_content(chunk_size=8192):
                f.write(chunk)
        print("[face_rec] SFace model downloaded successfully.")
    except Exception as e:
        print(f"[face_rec] Failed to download SFace model: {e}")
        # Delete partial file if failed
        if SFACE_MODEL_PATH.exists():
            try:
                SFACE_MODEL_PATH.unlink()
            except Exception:
                pass
        raise

def _get_net():
    """Lazily load and cache the SFace network."""
    global _net
    if _net is None:
        ensure_model_exists()
        _net = cv2.dnn.readNet(str(SFACE_MODEL_PATH))
    return _net

def load_model() -> bool:
    """Load the trained face recognition embeddings from disk. Returns True on success."""
    global _embeddings_db
    if not MODEL_PATH.exists():
        _embeddings_db = {}
        return False
    try:
        with MODEL_PATH.open("rb") as f:
            _embeddings_db = pickle.load(f)
        print(f"[face_rec] Loaded biometric database with {len(_embeddings_db)} profiles: {list(_embeddings_db.keys())}")
        return True
    except Exception as e:
        print(f"[face_rec] Failed to load model: {e}")
        _embeddings_db = {}
        return False

def detect_face(gray_img) -> tuple[int, int, int, int] | None:
    """Detect a single face in a grayscale image. Returns (x, y, w, h) of the largest face."""
    faces = _face_cascade.detectMultiScale(gray_img, scaleFactor=1.1, minNeighbors=5, minSize=(30, 30))
    if len(faces) == 0:
        return None
    # Return the largest face by area
    largest_face = max(faces, key=lambda rect: rect[2] * rect[3])
    return tuple(map(int, largest_face))

def _get_embedding(face_img) -> np.ndarray | None:
    """Generate 128-D embedding from BGR face image using SFace model."""
    try:
        net = _get_net()
        resized = cv2.resize(face_img, (112, 112))
        blob = cv2.dnn.blobFromImage(
            resized,
            scalefactor=1.0/255.0,
            size=(112, 112),
            mean=(0, 0, 0),
            swapRB=True,
            crop=False
        )
        net.setInput(blob)
        embedding = net.forward()[0]
        # L2 normalize
        norm = np.linalg.norm(embedding)
        if norm > 0:
            embedding = embedding / norm
        return embedding
    except Exception as e:
        print(f"[face_rec] Failed to extract embedding: {e}")
        return None

def train() -> str:
    """Extract embeddings from all face images in FACES_DIR and save them.

    Returns a status message.
    """
    global _embeddings_db
    if not FACES_DIR.exists():
        FACES_DIR.mkdir(parents=True, exist_ok=True)

    db: dict[str, list[np.ndarray]] = {}

    # Read each directory under FACES_DIR
    for name in sorted(os.listdir(FACES_DIR)):
        dir_path = FACES_DIR / name
        if not dir_path.is_dir() or name == "Negative":
            continue
        
        embeddings = []
        # Load images from this folder
        for file in os.listdir(dir_path):
            if file.lower().endswith((".jpg", ".jpeg", ".png")):
                img_path = dir_path / file
                img = cv2.imread(str(img_path))
                if img is None:
                    continue
                
                # If image is not 112x112, it might be a raw uncropped photo.
                # Try to crop it if so.
                if img.shape[0] != 112 or img.shape[1] != 112:
                    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
                    face_rect = detect_face(gray)
                    if face_rect:
                        x, y_coord, w, h = face_rect
                        cropped = img[y_coord : y_coord + h, x : x + w]
                    else:
                        cropped = img
                else:
                    cropped = img
                
                emb = _get_embedding(cropped)
                if emb is not None:
                    embeddings.append(emb)

        if embeddings:
            db[name] = embeddings

    if not db:
        return "No face images found in the database. Visage training aborted."

    try:
        with MODEL_PATH.open("wb") as f:
            pickle.dump(db, f)
        
        # Refresh cache
        _embeddings_db = db
        return f"Successfully trained biometric database with {len(db)} classes (profiles: {list(db.keys())})."
    except Exception as e:
        return f"Training failed: {e}"

def recognize(frame) -> str | None:
    """Analyze a frame. If a trained face is recognized with high confidence, return their name.

    Otherwise, returns None.
    """
    global _embeddings_db
    if not _embeddings_db:
        # Try loading if not cached
        if not load_model():
            return None

    try:
        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        face_rect = detect_face(gray)
        if not face_rect:
            return None

        # Crop and preprocess face
        x, y_coord, w, h = face_rect
        cropped = frame[y_coord : y_coord + h, x : x + w]
        
        embedding = _get_embedding(cropped)
        if embedding is None:
            return None

        best_name = None
        best_score = -1.0

        # Compare with all registered embeddings
        # SFace Cosine similarity matches return values in range [-1, 1]
        for name, vectors in _embeddings_db.items():
            for v in vectors:
                # Cosine similarity
                score = float(np.dot(v, embedding))
                if score > best_score:
                    best_score = score
                    best_name = name

        # SFace cosine similarity threshold is 0.363
        threshold = 0.363
        if best_score < threshold or best_name == "Unknown":
            print(f"[face_rec] Recognized face as '{best_name}' with score {best_score:.3f} (below threshold {threshold})")
            return None

        print(f"[face_rec] Match detected: {best_name} (score {best_score:.3f})")
        return best_name
    except Exception as e:
        print(f"[face_rec] Recognition error: {e}")
        return None

# Load the model on module import
load_model()
