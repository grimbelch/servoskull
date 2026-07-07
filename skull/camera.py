"""
Motion-triggered vision: detects movement, captures a frame, and asks
Claude Vision to describe what it sees in Omega-7 persona.

Runs in a background thread; observations are queued for main loop.
Activate by setting CAMERA_ENABLED=true in .env.

On Raspberry Pi with Camera Module 3: uses picamera2 (pre-installed on Pi OS).
On Mac/Windows (emulator): falls back to cv2.VideoCapture.
"""

from __future__ import annotations
import base64
import queue
import threading
import time

from skull import config

_observation_queue: queue.Queue = queue.Queue()
_last_observation_time: float = 0.0
_call_times: list[float] = []  # timestamps of recent vision calls (rolling hour)


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

    A backstop independent of motion/cooldown so a noisy sensor can't run
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
    "You have just detected movement with your optical sensors and captured this image. "
    f"Describe in one or two sentences what or who you observe, staying in character as {config.SKULL_NAME}. "
    "Be specific about what you see. No stage directions, no asterisks."
)


def _ask_vision(jpeg_bytes: bytes) -> str:
    from skull import llm
    return llm.vision(config.SYSTEM_PROMPT, jpeg_bytes, _VISION_PROMPT, max_tokens=150)


def _run_observation(jpeg_bytes: bytes) -> None:
    try:
        text = _ask_vision(jpeg_bytes)
        print(f"[camera] {text}")
        _observation_queue.put(text)
    except Exception as e:
        print(f"[camera] Vision error: {e}")


def _motion_loop_picamera2() -> None:
    global _last_observation_time
    import cv2
    import numpy as np
    from picamera2 import Picamera2

    picam2 = Picamera2()
    cam_cfg = picam2.create_preview_configuration(
        main={"size": (640, 480), "format": "RGB888"}
    )
    picam2.configure(cam_cfg)
    picam2.start()
    print("[camera] Motion detection active (picamera2 / IMX708)")

    frame = picam2.capture_array()
    prev_gray = cv2.GaussianBlur(cv2.cvtColor(frame, cv2.COLOR_RGB2GRAY), (21, 21), 0)

    while True:
        time.sleep(0.1)
        frame = picam2.capture_array()
        gray = cv2.GaussianBlur(cv2.cvtColor(frame, cv2.COLOR_RGB2GRAY), (21, 21), 0)
        diff = cv2.absdiff(prev_gray, gray)
        _, thresh = cv2.threshold(diff, 25, 255, cv2.THRESH_BINARY)
        motion_score = int(np.sum(thresh) // 255)
        prev_gray = gray

        now = time.time()
        if (motion_score >= config.CAMERA_MOTION_THRESHOLD
                and now - _last_observation_time >= config.CAMERA_COOLDOWN):
            _last_observation_time = now
            clean = picam2.capture_array()
            clean_gray = cv2.cvtColor(clean, cv2.COLOR_RGB2GRAY)
            if _is_blank(clean_gray):
                print(f"[camera] Motion (score={motion_score}) but frame is blank/dark — skipping vision")
                continue
            if _rate_limited():
                print("[camera] Per-hour vision-call limit reached — skipping")
                continue
            print(f"[camera] Motion detected (score={motion_score}) — querying vision")
            bgr = cv2.cvtColor(clean, cv2.COLOR_RGB2BGR)
            _, buf = cv2.imencode(".jpg", bgr, [cv2.IMWRITE_JPEG_QUALITY, 75])
            _run_observation(buf.tobytes())


def _motion_loop_cv2() -> None:
    global _last_observation_time
    import cv2
    import numpy as np

    cap = cv2.VideoCapture(config.CAMERA_DEVICE_INDEX)
    if not cap.isOpened():
        print(f"[camera] Could not open device {config.CAMERA_DEVICE_INDEX} — vision disabled")
        return

    print(f"[camera] Motion detection active (cv2 / device {config.CAMERA_DEVICE_INDEX})")

    ret, frame = cap.read()
    if not ret:
        cap.release()
        return

    prev_gray = cv2.GaussianBlur(cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY), (21, 21), 0)

    while True:
        time.sleep(0.1)
        ret, frame = cap.read()
        if not ret:
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
            ret2, clean = cap.read()
            if not ret2:
                continue
            clean_gray = cv2.cvtColor(clean, cv2.COLOR_BGR2GRAY)
            if _is_blank(clean_gray):
                print(f"[camera] Motion (score={motion_score}) but frame is blank/dark — skipping vision")
                continue
            if _rate_limited():
                print("[camera] Per-hour vision-call limit reached — skipping")
                continue
            print(f"[camera] Motion detected (score={motion_score}) — querying vision")
            _, buf = cv2.imencode(".jpg", clean, [cv2.IMWRITE_JPEG_QUALITY, 75])
            _run_observation(buf.tobytes())

    cap.release()


def _motion_loop() -> None:
    try:
        import picamera2  # noqa: F401
        _motion_loop_picamera2()
    except ImportError:
        _motion_loop_cv2()


def start() -> None:
    """Start background motion detection. No-op if CAMERA_ENABLED is false."""
    if not config.CAMERA_ENABLED:
        return
    threading.Thread(target=_motion_loop, daemon=True).start()


def get_observation() -> str | None:
    """Return a pending vision observation, or None if the queue is empty."""
    try:
        return _observation_queue.get_nowait()
    except queue.Empty:
        return None
