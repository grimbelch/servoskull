"""
Proximity-triggered vision: notices someone nearby, captures a frame, and asks
Claude Vision to describe what it sees in Omega-7 persona.

Trigger source, chosen automatically at startup:
  * VL53L1X time-of-flight sensor (proximity.py) when present — fires on genuine
    physical approach and works in the dark.
  * Frame-difference motion detection otherwise — the fallback used by the
    Mac/Windows emulator and any Pi without the sensor wired.

Runs in a background thread; observations are queued for the main loop.
Activate by setting CAMERA_ENABLED=true in .env (and PROXIMITY_ENABLED=true to
use the ToF sensor).

On Raspberry Pi with Camera Module 3: uses picamera2 (pre-installed on Pi OS).
On Mac/Windows (emulator): falls back to cv2.VideoCapture.
"""

from __future__ import annotations
import queue
import threading
import time

from skull import config, proximity

_observation_queue: queue.Queue = queue.Queue()
_last_observation_time: float = 0.0
_call_times: list[float] = []  # timestamps of recent vision calls (rolling hour)

_read_frame_fn = None
_camera_lock = threading.Lock()


def _is_blank(gray) -> bool:
    """True if the frame is too dark or too uniform to be worth describing.

    Guards against sending covered-lens, unlit-room, or garbage frames to
    Claude. `gray` is a single-channel uint8 image.
    """
    import numpy as np
    mean = float(np.mean(gray))
    std = float(np.std(gray))
    # Dark frame, or near-flat frame (no detail) -> treat as blank.
    return mean < config.CAMERA_MIN_BRIGHTNESS or std < 8.0


def _rate_limited() -> bool:
    """True if we've already hit the per-hour vision-call ceiling.

    A backstop independent of the trigger/cooldown so a noisy sensor can't run
    away with the API budget. Prunes timestamps older than one hour.
    """
    now = time.time()
    cutoff = now - 3600.0
    _call_times[:] = [t for t in _call_times if t >= cutoff]
    if len(_call_times) >= config.CAMERA_MAX_PER_HOUR:
        return True
    _call_times.append(now)
    return False


_VISION_PROMPT = (
    "You have just sensed someone or something nearby and captured this image. "
    f"Describe in one or two sentences what or who you observe, staying in character as {config.SKULL_NAME}. "
    "Be specific about what you see. No stage directions, no asterisks."
)


def _ask_vision(jpeg_bytes: bytes, detected_name: str | None = None) -> str:
    from skull import llm
    prompt = _VISION_PROMPT
    if detected_name:
        prompt = f"[Biometric Scanner: Detected visage of user '{detected_name}'] " + prompt
    return llm.vision(config.SYSTEM_PROMPT, jpeg_bytes, prompt, max_tokens=150)


def _run_observation(jpeg_bytes: bytes) -> None:
    # Deprecated fallback since observations now run face_rec in main thread
    from skull import display as _display
    _display.set_targeting(True)
    try:
        text = _ask_vision(jpeg_bytes)
        print(f"[camera] {text}")
        _observation_queue.put(text)
    except Exception as e:
        print(f"[camera] Vision error: {e}")
    finally:
        _display.set_targeting(False)


def _open_backend():
    """Set up a frame source and return (read, close).

    read() -> a BGR uint8 frame (numpy array) or None on failure.
    close() releases the device.

    Prefers picamera2 (Pi Camera Module 3 / IMX708); falls back to
    cv2.VideoCapture on the emulator. Returns None if no camera can be opened.
    """
    try:
        from picamera2 import Picamera2
    except ImportError:
        return _open_cv2_backend()

    import cv2
    picam2 = Picamera2()
    picam2.configure(
        picam2.create_preview_configuration(main={"size": (640, 480), "format": "RGB888"})
    )
    picam2.start()
    print("[camera] Frame source: picamera2 / IMX708")

    def read():
        rgb = picam2.capture_array()
        bgr = cv2.cvtColor(rgb, cv2.COLOR_RGB2BGR)
        return cv2.rotate(bgr, cv2.ROTATE_90_COUNTERCLOCKWISE)

    def close():
        picam2.stop()

    return read, close


def _open_cv2_backend():
    import cv2
    cap = cv2.VideoCapture(config.CAMERA_DEVICE_INDEX)
    if not cap.isOpened():
        print(f"[camera] Could not open device {config.CAMERA_DEVICE_INDEX} — vision disabled")
        return None
    print(f"[camera] Frame source: cv2 / device {config.CAMERA_DEVICE_INDEX}")

    def read():
        ret, frame = cap.read()
        if not ret or frame is None:
            return None
        return cv2.rotate(frame, cv2.ROTATE_90_COUNTERCLOCKWISE)

    def close():
        cap.release()

    return read, close


def _capture_and_observe(read, reason: str) -> None:
    """Grab a clean frame and, unless it's blank or we're rate-limited, describe it.

    Cooldown is the caller's responsibility (set before this runs) so even a
    blank/rate-limited trigger still resets it and we don't hammer the sensor.
    """
    import cv2
    with _camera_lock:
        frame = read()
    if frame is None:
        return
    gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
    if _is_blank(gray):
        print(f"[camera] {reason} but frame is blank/dark — skipping vision")
        return
    if _rate_limited():
        print("[camera] Per-hour vision-call limit reached — skipping")
        return

    # Check biometrics
    from skull import face_rec
    detected_name = face_rec.recognize(frame)

    print(f"[camera] {reason} — querying vision (biometrics: {detected_name})")
    _, buf = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, 75])
    
    # Run vision
    from skull import display as _display
    _display.set_targeting(True)
    try:
        text = _ask_vision(buf.tobytes(), detected_name)
        print(f"[camera] {text}")
        _observation_queue.put(text)
    except Exception as e:
        print(f"[camera] Vision error: {e}")
    finally:
        _display.set_targeting(False)


def _proximity_trigger_loop(read) -> None:
    """Fire vision whenever a target comes within PROXIMITY_THRESHOLD_CM."""
    global _last_observation_time
    print("[camera] Proximity-triggered vision active (VL53L1X)")
    while True:
        time.sleep(config.PROXIMITY_POLL_INTERVAL)
        cm = proximity.read_cm()
        if cm is None:
            continue
        now = time.time()
        if (cm <= config.PROXIMITY_THRESHOLD_CM
                and now - _last_observation_time >= config.CAMERA_COOLDOWN):
            _last_observation_time = now
            _capture_and_observe(read, f"Proximity {cm:.0f}cm")


def _motion_trigger_loop(read) -> None:
    """Fallback: fire vision on frame-difference motion above the threshold."""
    global _last_observation_time
    import cv2
    import numpy as np

    print("[camera] Motion-triggered vision active (frame differencing)")
    with _camera_lock:
        frame = read()
    if frame is None:
        return
    prev_gray = cv2.GaussianBlur(cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY), (21, 21), 0)

    while True:
        time.sleep(0.1)
        with _camera_lock:
            frame = read()
        if frame is None:
            continue

        gray = cv2.GaussianBlur(cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY), (21, 21), 0)
        diff = cv2.absdiff(prev_gray, gray)
        _, thresh = cv2.threshold(diff, 25, 255, cv2.THRESH_BINARY)
        motion_score = int(np.sum(thresh) // 255)
        prev_gray = gray

        now = time.time()
        if (motion_score >= config.CAMERA_MOTION_THRESHOLD
                and now - _last_observation_time >= config.CAMERA_COOLDOWN):
            _last_observation_time = now
            _capture_and_observe(read, f"Motion (score={motion_score})")


def _vision_loop() -> None:
    global _read_frame_fn
    backend = _open_backend()
    if backend is None:
        return
    read, close = backend
    _read_frame_fn = read
    try:
        if proximity.start():
            _proximity_trigger_loop(read)
        else:
            _motion_trigger_loop(read)
    finally:
        _read_frame_fn = None
        close()
        proximity.stop()


def start() -> None:
    """Start background vision triggering. No-op if CAMERA_ENABLED is false."""
    if not config.CAMERA_ENABLED:
        return
    threading.Thread(target=_vision_loop, daemon=True).start()


def get_observation() -> str | None:
    """Return a pending vision observation, or None if the queue is empty."""
    try:
        return _observation_queue.get_nowait()
    except queue.Empty:
        return None


def capture_on_demand() -> str:
    """Capture a single frame using the active camera backend and describe it."""
    if not config.CAMERA_ENABLED:
        return "Camera interface is disabled in configuration."
    
    # If the background loop is not running, open/close the backend on-demand
    if _read_frame_fn is None:
        backend = _open_backend()
        if backend is None:
            return "No camera backend could be initialized."
        read, close = backend
        try:
            import cv2
            from skull import display as _display
            from skull import face_rec
            _display.set_targeting(True)
            frame = read()
            if frame is None:
                return "Failed to capture frame from camera."
            
            detected_name = face_rec.recognize(frame)
            _, buf = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, 75])
            desc = _ask_vision(buf.tobytes(), detected_name)
            return desc
        except Exception as e:
            return f"Failed to capture or describe image: {e}"
        finally:
            _display.set_targeting(False)
            close()
            
    # If the background loop is already running, share its reader using the lock
    import cv2
    from skull import display as _display
    from skull import face_rec
    _display.set_targeting(True)
    try:
        with _camera_lock:
            frame = _read_frame_fn()
        if frame is None:
            return "Failed to capture frame from camera."
        
        detected_name = face_rec.recognize(frame)
        _, buf = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, 75])
        desc = _ask_vision(buf.tobytes(), detected_name)
        return desc
    except Exception as e:
        return f"Failed to capture or describe image: {e}"
    finally:
        _display.set_targeting(False)


def register_face(name: str) -> str:
    """Capture a series of face images over 5 seconds to train face recognition."""
    if not config.CAMERA_ENABLED:
        return "Camera interface is disabled in configuration."
    
    # Check if reader is available
    if _read_frame_fn is None:
        backend = _open_backend()
        if backend is None:
            return "No camera backend could be initialized for visage calibration."
        read, close = backend
    else:
        read = _read_frame_fn
        close = None
        
    import cv2
    from skull import display as _display
    from skull import sfx
    from skull import face_rec
    
    # Create directory for name
    target_dir = face_rec.FACES_DIR / name
    target_dir.mkdir(parents=True, exist_ok=True)
    
    print(f"[camera] Visage calibration started for: {name}")
    captured_count = 0
    
    _display.set_targeting(True)
    try:
        # Capture 10 frames with 0.5s interval
        for i in range(10):
            time.sleep(0.5)
            with _camera_lock:
                frame = read()
            if frame is None:
                continue
                
            gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
            face_rect = face_rec.detect_face(gray)
            if face_rect:
                x, y_coord, w, h = face_rect
                cropped = frame[y_coord : y_coord + h, x : x + w]
                # Save cropped BGR face
                face_path = target_dir / f"face_{captured_count}_{int(time.time())}.jpg"
                cv2.imwrite(str(face_path), cropped)
                captured_count += 1
                
                # Play audio indicator
                sfx.play("servo_whir")
                
        if captured_count >= 5:
            # Run training pipeline
            train_msg = face_rec.train()
            return f"Visage registered successfully. Captured {captured_count} facial frames. {train_msg}"
        else:
            return f"Visage calibration failed. Only captured {captured_count}/10 valid facial frames. Please ensure adequate lighting and align your face in front of my ocular sensor."
            
    except Exception as e:
        return f"Visage registration failed due to error: {e}"
    finally:
        _display.set_targeting(False)
        if close:
            close()
