"""
Manages the LinApple-pie Apple II emulator process and Xvfb virtual framebuffer
for autonomous Bard's Tale gameplay on Omega-7.

Pi apt dependencies:  sudo apt install xvfb linapple xdotool
Python pip dependency: python-xlib  (Pillow already present in the project)

All public functions are safe to call from any thread. The module is a no-op if
linapple or Xvfb are not installed — it prints a clear error and returns False/None
so the rest of the system never crashes.
"""

from __future__ import annotations
import os
import pathlib
import subprocess
import threading
import time
from typing import Optional

try:
    from PIL import Image
    _PIL_AVAILABLE = True
except ImportError:
    _PIL_AVAILABLE = False
    Image = None  # type: ignore

try:
    from Xlib import display as _xlib_display, X as _X
    _XLIB_AVAILABLE = True
except ImportError:
    _XLIB_AVAILABLE = False

# ── Configuration ────────────────────────────────────────────────────────────────
DISPLAY_NUM  = ":99"                  # virtual display number for Xvfb
_XVFB_GEOM  = "560x384x24"           # 2× Apple II resolution (280×192), 24-bit colour
_BOOT_DELAY  = 2.5                    # seconds to wait for the emulator to render frame 1

# ── Module state ─────────────────────────────────────────────────────────────────
_lock          = threading.Lock()
_xvfb_proc:    Optional[subprocess.Popen] = None
_apple_proc:   Optional[subprocess.Popen] = None
_window_id:    Optional[str]              = None
_xlib_dpy                                = None   # cached Xlib connection


# ── Internal helpers ─────────────────────────────────────────────────────────────

def _get_xlib_display():
    """Return (and cache) an Xlib Display connection to the virtual framebuffer."""
    global _xlib_dpy
    if not _XLIB_AVAILABLE:
        return None
    try:
        if _xlib_dpy is None:
            _xlib_dpy = _xlib_display.Display(DISPLAY_NUM)
        return _xlib_dpy
    except Exception as e:
        print(f"[emulator] Xlib connect error: {e}")
        _xlib_dpy = None
        return None


def _env() -> dict:
    """Return os.environ merged with DISPLAY pointing at our virtual framebuffer."""
    return {**os.environ, "DISPLAY": DISPLAY_NUM}


# ── Public API ───────────────────────────────────────────────────────────────────

def start(disk_path: str) -> bool:
    """
    Launch Xvfb and LinApple against *disk_path*.

    Returns True when the emulator is running, False if any dependency is missing.
    Safe to call when already running — returns True immediately.
    """
    global _xvfb_proc, _apple_proc, _window_id, _xlib_dpy

    with _lock:
        # Already running?
        if _apple_proc and _apple_proc.poll() is None:
            return True

        # ── 1. Start Xvfb ────────────────────────────────────────────────────
        try:
            _xvfb_proc = subprocess.Popen(
                ["Xvfb", DISPLAY_NUM, "-screen", "0", _XVFB_GEOM],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
        except FileNotFoundError:
            print("[emulator] Xvfb not found. Install: sudo apt install xvfb")
            return False

        time.sleep(0.8)         # wait for the display to be ready
        _xlib_dpy = None        # reset cached connection after new Xvfb

        # ── 2. Start LinApple ────────────────────────────────────────────────
        disk_path = str(pathlib.Path(disk_path).resolve())
        try:
            _apple_proc = subprocess.Popen(
                ["linapple", "--d1", disk_path, "--autoboot"],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                env=_env(),
            )
        except FileNotFoundError:
            print("[emulator] linapple not found. Install: sudo apt install linapple")
            _xvfb_proc.terminate()
            _xvfb_proc = None
            return False

        time.sleep(_BOOT_DELAY)     # wait for first frame

        # ── 3. Resolve xdotool window ID ─────────────────────────────────────
        try:
            result = subprocess.run(
                ["xdotool", "search", "--pid", str(_apple_proc.pid)],
                capture_output=True, text=True,
                env=_env(), timeout=5,
            )
            wids = result.stdout.strip().split()
            _window_id = wids[0] if wids else None
        except Exception as e:
            print(f"[emulator] xdotool window search failed: {e}")
            _window_id = None

        print(f"[emulator] LinApple started — PID {_apple_proc.pid}, "
              f"window {_window_id or '(unknown)'}")
        return True


def stop() -> None:
    """Terminate LinApple and Xvfb cleanly."""
    global _xvfb_proc, _apple_proc, _window_id, _xlib_dpy

    with _lock:
        for proc in (_apple_proc, _xvfb_proc):
            if proc is None:
                continue
            try:
                proc.terminate()
                proc.wait(timeout=3)
            except Exception:
                try:
                    proc.kill()
                except Exception:
                    pass

        if _xlib_dpy is not None:
            try:
                _xlib_dpy.close()
            except Exception:
                pass
            _xlib_dpy = None

        _apple_proc = _xvfb_proc = _window_id = None
        print("[emulator] Stopped.")


def send_key(key: str) -> None:
    """
    Inject *key* into the LinApple window via xdotool.

    *key* should be an xdotool key name: "w", "Return", "space", "1" … "9", etc.
    No-op if the emulator is not running.
    """
    if not is_running():
        return
    try:
        cmd = ["xdotool", "key"]
        if _window_id:
            cmd += ["--window", _window_id]
        cmd.append(key)
        subprocess.run(cmd, capture_output=True, env=_env(), timeout=2)
    except Exception as e:
        print(f"[emulator] send_key({key!r}) error: {e}")


def capture_frame() -> Optional["Image.Image"]:
    """
    Screenshot the Xvfb display and return a 240×240 PIL Image with the
    circular crop applied, ready to blit to the GC9A01 skull display.

    Returns None if Xlib or PIL are unavailable, or if capture fails.
    """
    if not _PIL_AVAILABLE:
        return None

    dpy = _get_xlib_display()
    if dpy is None:
        return None

    try:
        root = dpy.screen().root
        geom = root.get_geometry()
        raw  = root.get_image(0, 0, geom.width, geom.height, _X.ZPixmap, 0xFFFFFFFF)
        # Xlib returns pixel data as BGRA on little-endian systems
        img  = Image.frombytes(
            "RGBA", (geom.width, geom.height), raw.data, "raw", "BGRA"
        ).convert("RGB")
    except Exception as e:
        print(f"[emulator] capture_frame error: {e}")
        return None

    # ── Crop to centred square, then scale to 240×240 ────────────────────────
    w, h  = img.size
    side  = min(w, h)
    left  = (w - side) // 2
    top   = (h - side) // 2
    img   = img.crop((left, top, left + side, top + side))
    img   = img.resize((240, 240), Image.LANCZOS)
    return img


def is_running() -> bool:
    """Return True while the LinApple subprocess is alive."""
    return _apple_proc is not None and _apple_proc.poll() is None
