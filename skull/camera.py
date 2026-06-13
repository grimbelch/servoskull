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

_VISION_PROMPT = (
    "You have just detected movement with your optical sensors and captured this image. "
    "Describe in one or two sentences what or who you observe, staying in character as Omega-7. "
    "Be specific about what you see. No stage directions, no asterisks."
)


def _ask_claude_vision(jpeg_bytes: bytes) -> str:
    from anthropic import Anthropic
    client = Anthropic(api_key=config.ANTHROPIC_API_KEY)
    b64 = base64.standard_b64encode(jpeg_bytes).decode()
    response = client.messages.create(
        model=config.CLAUDE_MODEL,
        max_tokens=150,
        system=config.SYSTEM_PROMPT,
        messages=[{
            "role": "user",
            "content": [
                {
                    "type": "image",
                    "source": {
                        "type": "base64",
                        "media_type": "image/jpeg",
                        "data": b64,
                    },
                },
                {"type": "text", "text": _VISION_PROMPT},
            ],
        }],
    )
    return response.content[0].text.strip()


def _run_observation(jpeg_bytes: bytes) -> None:
    try:
        text = _ask_claude_vision(jpeg_bytes)
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
            print(f"[camera] Motion detected (score={motion_score}) — querying vision")
            clean = picam2.capture_array()
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
            print(f"[camera] Motion detected (score={motion_score}) — querying vision")
            ret2, clean = cap.read()
            if not ret2:
                continue
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
