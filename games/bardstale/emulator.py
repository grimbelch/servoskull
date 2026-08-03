"""
MAME-based Apple IIe emulator wrapper for Bard's Tale autonomous gameplay.
Drop-in replacement for the linapple backend.

Pi apt dependency:  sudo apt install mame xvfb xdotool
Python pip:         python-xlib  (Pillow already present)

ROM requirement
───────────────
MAME needs apple2e.zip (Apple IIe system ROMs) in its ROM path.
Default location: ~/.mame/roms/apple2e.zip
The ROM archive is freely available from the Internet Archive.

Disk format
───────────
MAME supports: .dsk  .do  .po  .nib  .woz  .2mg
⚠  .d64 is the Commodore 64 format — NOT compatible.
   You need the Apple II edition of Bard's Tale.

Public API (unchanged from the linapple backend)
────────────────────────────────────────────────
  start(disk_path) -> bool
  stop()
  send_key(key: str)
  capture_frame() -> PIL.Image | None
  is_running() -> bool
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

# ── Configuration ─────────────────────────────────────────────────────────────
DISPLAY_NUM  = ":99"
_XVFB_GEOM   = "560x384x24"    # Apple IIe native × 2; MAME fullscreen fills it
_MAME_DRIVER = "apple2e"        # MAME system driver (covers Bard's Tale original)
_BOOT_DELAY  = 5.0              # seconds for MAME to initialise and show first frame

# MAME flags. -fullscreen fills the Xvfb display without a title bar, giving us
# a clean game image to crop.  -sound none stops MAME from fighting the Pi's
# ALSA device (Omega-7's audio stack handles all sound).
_MAME_FLAGS: list[str] = [
    "-fullscreen",
    "-skip_gameinfo",
    "-sound",     "none",
    "-video",     "soft",      # software renderer — safe with Xvfb / X11
    "-noautosave",
]

# ROM search path for MAME.
# Default: the games/ root directory alongside this package — a single shared
# location for all future emulated systems (e.g. games/apple2e.zip).
# Override with the MAME_ROMPATH environment variable if needed.
_ROMPATH: str = os.environ.get(
    "MAME_ROMPATH",
    str(pathlib.Path(__file__).resolve().parent.parent),  # → …/Servoskull/games/
)

# ── Module state ───────────────────────────────────────────────────────────────
_lock        = threading.Lock()
_xvfb_proc:  Optional[subprocess.Popen] = None
_mame_proc:  Optional[subprocess.Popen] = None
_window_id:  Optional[str]              = None
_xlib_dpy                               = None


# ── Internal helpers ───────────────────────────────────────────────────────────

def _get_xlib_display():
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


def _build_env() -> dict:
    """Return env dict pointing SDL2 and the display at our virtual framebuffer."""
    return {
        **os.environ,
        "DISPLAY":          DISPLAY_NUM,
        "SDL_VIDEODRIVER":  "x11",      # force SDL2 to use X11 (works with Xvfb)
    }


# ── Public API ─────────────────────────────────────────────────────────────────

def start(disk_path: str) -> bool:
    """
    Launch Xvfb and MAME apple2e with *disk_path* as the floppy image.
    Returns True when the emulator is up, False on missing dependency or ROM error.
    Safe to call when already running — returns True immediately.
    """
    global _xvfb_proc, _mame_proc, _window_id, _xlib_dpy

    with _lock:
        if _mame_proc and _mame_proc.poll() is None:
            return True

        # ── 1. Virtual framebuffer ────────────────────────────────────────────
        try:
            _xvfb_proc = subprocess.Popen(
                ["Xvfb", DISPLAY_NUM, "-screen", "0", _XVFB_GEOM],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                restore_signals=False,
            )
        except FileNotFoundError:
            print("[emulator] Xvfb not found. Install: sudo apt install xvfb")
            return False

        time.sleep(0.8)
        _xlib_dpy = None    # reset cached Xlib connection

        # ── 2. MAME ───────────────────────────────────────────────────────────
        disk_path_obj = pathlib.Path(disk_path).resolve()
        other_disks = [
            str(p) for p in sorted(list(disk_path_obj.parent.glob("*.dsk")) + list(disk_path_obj.parent.glob("*.woz")) + list(disk_path_obj.parent.glob("*.po")))
            if p.resolve() != disk_path_obj
        ]
        cmd = ["mame", _MAME_DRIVER, "-flop1", str(disk_path_obj)]
        if other_disks:
            cmd += ["-flop2", other_disks[0]]
            print(f"[emulator] Mounted drive 2 (-flop2): {other_disks[0]}")
        cmd += _MAME_FLAGS
        cmd += ["-rompath", _ROMPATH]

        try:
            _mame_proc = subprocess.Popen(
                cmd,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                env=_build_env(),
                restore_signals=False,
            )
        except FileNotFoundError:
            print("[emulator] mame not found. Install: sudo apt install mame")
            _xvfb_proc.terminate()
            _xvfb_proc = None
            return False

        time.sleep(_BOOT_DELAY)

        # ── 3. Resolve window for xdotool ─────────────────────────────────────
        if _mame_proc.poll() is not None:
            # MAME exited immediately — almost certainly a missing ROM
            print("[emulator] MAME exited during boot. "
                  "Check that ~/.mame/roms/apple2e.zip exists and disk format is "
                  ".dsk/.po/.nib/.woz (NOT .d64).")
            _xvfb_proc.terminate()
            _xvfb_proc = _mame_proc = None
            return False

        try:
            result = subprocess.run(
                ["xdotool", "search", "--pid", str(_mame_proc.pid)],
                capture_output=True, text=True,
                env=_build_env(), timeout=5,
                restore_signals=False,
            )
            wids = result.stdout.strip().split()
            _window_id = wids[0] if wids else None
        except Exception as e:
            print(f"[emulator] xdotool search error: {e}")
            _window_id = None

        print(f"[emulator] MAME apple2e started — PID {_mame_proc.pid}, "
              f"window {_window_id or '(unknown)'}, disk: {disk_path}")
        return True


def stop() -> None:
    """Terminate MAME and Xvfb cleanly."""
    global _xvfb_proc, _mame_proc, _window_id, _xlib_dpy

    with _lock:
        for proc in (_mame_proc, _xvfb_proc):
            if proc is None:
                continue
            try:
                proc.terminate()
                proc.wait(timeout=4)
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

        _mame_proc = _xvfb_proc = _window_id = None
        print("[emulator] Stopped.")


def send_key(key: str) -> None:
    """
    Inject *key* into the MAME window via xdotool.

    Uses --clearmodifiers so stray Shift/Ctrl states don't corrupt input.
    xdotool key names: "w" "a" "s" "d" "f" "c" "r"
                       "Return" "space" "1" … "9"
    """
    if not is_running():
        return
    env = _build_env()
    try:
        cmd = ["xdotool", "key", "--clearmodifiers"]
        if _window_id:
            cmd += ["--window", _window_id]
        cmd.append(key)
        subprocess.run(cmd, capture_output=True, env=env, timeout=2, restore_signals=False)
    except Exception as e:
        print(f"[emulator] send_key({key!r}) error: {e}")


def capture_frame() -> Optional["Image.Image"]:
    """
    Screenshot the Xvfb display and return a 240×240 PIL Image, ready to blit.

    MAME runs fullscreen inside Xvfb at 560×384.  We grab the root window,
    centre-crop to a 384×384 square (keeping the dungeon view), and scale to
    240×240 for the GC9A01 skull display.
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
        img  = Image.frombytes(
            "RGBA", (geom.width, geom.height), raw.data, "raw", "BGRA"
        ).convert("RGB")
    except Exception as e:
        print(f"[emulator] capture_frame error: {e}")
        return None

    # Centre-crop to square then scale to skull display resolution
    w, h  = img.size
    side  = min(w, h)
    left  = (w - side) // 2
    top   = (h - side) // 2
    img   = img.crop((left, top, left + side, top + side))
    img   = img.resize((240, 240), Image.LANCZOS)
    return img


def is_running() -> bool:
    """Return True while MAME is alive."""
    return _mame_proc is not None and _mame_proc.poll() is None
