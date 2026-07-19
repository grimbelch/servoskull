"""
Lightweight biometric face recognition module using OpenCV Haar Cascades and scikit-learn.
Keeps biometric profiles stored in USER_DATA_DIR/faces/ and trains a PCA + KNN classifier.
"""

from __future__ import annotations
import os
import pickle
import pathlib
import numpy as np
import cv2
from skull import config

# Directory where face profiles are stored
FACES_DIR = pathlib.Path(config.data_path("faces"))
MODEL_PATH = FACES_DIR / "face_model.pkl"

# Load the face detector Cascade
_cascade_path = cv2.data.haarcascades + "haarcascade_frontalface_default.xml"
_face_cascade = cv2.CascadeClassifier(_cascade_path)

# Active trained model cache
_trained_model = None
_label_names = []


def load_model() -> bool:
    """Load the trained face recognition model from disk. Returns True on success."""
    global _trained_model, _label_names
    if not MODEL_PATH.exists():
        _trained_model = None
        _label_names = []
        return False
    try:
        with MODEL_PATH.open("rb") as f:
            data = pickle.load(f)
            _trained_model = data["model"]
            _label_names = data["labels"]
        print(f"[face_rec] Loaded biometric database: {_label_names}")
        return True
    except Exception as e:
        print(f"[face_rec] Failed to load model: {e}")
        _trained_model = None
        _label_names = []
        return False


def detect_face(gray_img) -> tuple[int, int, int, int] | None:
    """Detect a single face in a grayscale image. Returns (x, y, w, h) of the largest face."""
    faces = _face_cascade.detectMultiScale(gray_img, scaleFactor=1.1, minNeighbors=5, minSize=(30, 30))
    if len(faces) == 0:
        return None
    # Return the largest face by area
    largest_face = max(faces, key=lambda rect: rect[2] * rect[3])
    return tuple(map(int, largest_face))


def train() -> str:
    """Train the face recognition classifier using files in FACES_DIR.

    Returns a status message.
    """
    global _trained_model, _label_names
    from sklearn.decomposition import PCA
    from sklearn.neighbors import KNeighborsClassifier
    from sklearn.pipeline import Pipeline

    if not FACES_DIR.exists():
        FACES_DIR.mkdir(parents=True, exist_ok=True)

    # 1. Gather all training images
    X = []
    y = []
    labels = []

    # Read each directory under FACES_DIR
    for idx, name in enumerate(sorted(os.listdir(FACES_DIR))):
        dir_path = FACES_DIR / name
        if not dir_path.is_dir() or name == "Negative":
            continue
        
        # Load images from this folder
        face_images = []
        for file in os.listdir(dir_path):
            if file.lower().endswith((".jpg", ".jpeg", ".png")):
                img_path = dir_path / file
                img = cv2.imread(str(img_path))
                if img is None:
                    continue
                gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
                # Check if it is already cropped, if not, try to crop it
                if gray.shape == (64, 64):
                    face_images.append(gray)
                else:
                    face_rect = detect_face(gray)
                    if face_rect:
                        x, y_coord, w, h = face_rect
                        cropped = gray[y_coord : y_coord + h, x : x + w]
                        resized = cv2.resize(cropped, (64, 64))
                        face_images.append(resized)
                    elif gray.shape[0] < 150 and gray.shape[1] < 150:
                        # If image is already small, assume it is already a cropped face
                        resized = cv2.resize(gray, (64, 64))
                        face_images.append(resized)

        if face_images:
            labels.append(name)
            label_idx = len(labels) - 1
            for face in face_images:
                X.append(face.flatten())
                y.append(label_idx)

    if not X:
        return "No face images found in the database. Visage training aborted."

    # 2. Handle 1-class training using a synthetic Negative class
    # If there's only 1 real class, add 10 synthetic negative/unknown samples (gradients and noise)
    # so that the classifier has a second category to prevent false-positives.
    if len(labels) == 1:
        labels.append("Unknown")
        neg_label_idx = len(labels) - 1
        # Generate synthetic patterns (noise, gradients, checks)
        for i in range(10):
            # Gradient
            grad = np.linspace(0, 255, 64).astype(np.uint8)
            grid = np.tile(grad, (64, 1)) if i % 2 == 0 else np.tile(grad[:, np.newaxis], (1, 64))
            # Add some noise
            noise = np.random.randint(-20, 20, (64, 64))
            neg = np.clip(grid + noise, 0, 255).astype(np.uint8)
            X.append(neg.flatten())
            y.append(neg_label_idx)

    X = np.array(X)
    y = np.array(y)

    n_samples = X.shape[0]
    n_components = min(15, n_samples - 1) if n_samples > 1 else 1

    # 3. Create PCA + KNN pipeline
    # PCA reduces the 4096-dim vector to principal components
    # KNN classifies using distance in PCA space
    pipeline = Pipeline([
        ("pca", PCA(n_components=n_components, whiten=True)),
        ("knn", KNeighborsClassifier(n_neighbors=min(3, n_samples), weights="distance"))
    ])

    try:
        pipeline.fit(X, y)
        # Save to disk
        data = {"model": pipeline, "labels": labels}
        with MODEL_PATH.open("wb") as f:
            pickle.dump(data, f)
        
        # Refresh cache
        _trained_model = pipeline
        _label_names = labels
        return f"Successfully trained biometric database with {len(labels)} classes (profiles: {labels})."
    except Exception as e:
        return f"Training failed: {e}"


def recognize(frame) -> str | None:
    """Analyze a frame. If a trained face is recognized with high confidence, return their name.

    Otherwise, returns None.
    """
    global _trained_model, _label_names
    if _trained_model is None:
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
        cropped = gray[y_coord : y_coord + h, x : x + w]
        resized = cv2.resize(cropped, (64, 64))
        flat = resized.flatten().reshape(1, -1)

        # Classify
        pred_idx = int(_trained_model.predict(flat)[0])
        name = _label_names[pred_idx]

        # Check prediction confidence (probability estimation)
        # KNeighborsClassifier with 'weights=distance' supports predict_proba
        proba = _trained_model.predict_proba(flat)[0]
        confidence = float(proba[pred_idx])

        # If it's the negative class or confidence is too low, treat as unrecognized
        if name == "Unknown" or confidence < 0.65:
            print(f"[face_rec] Recognized face as '{name}' with confidence {confidence:.2f} (below threshold)")
            return None

        print(f"[face_rec] Match detected: {name} (confidence {confidence:.2f})")
        return name
    except Exception as e:
        print(f"[face_rec] Recognition error: {e}")
        return None

# Load the model on module import
load_model()
