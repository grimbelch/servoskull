"""
Headless Apple IIe (MAME) for Omega-7's Bard's Tale player.

MAME runs with no window and no sound (-video none -sound none); control.lua is
its only interface. Python and Lua talk through small files in a tmpfs directory,
so nothing here touches X11 or the SD card per frame:

    keys / disk swaps / save states  ->  RUN_DIR/cmd       (Lua executes, deletes)
    screen pixels                    <-  RUN_DIR/frame     (rewritten when it changes)

Requirements on the Pi: `sudo apt install mame`, and the Apple IIe ROM sets
(apple2e.zip, a2diskiing.zip, d2fdc.zip) in ~/.mame/roms or BARDSTALE_ROMPATH.

The pristine disk images in games/bardstale/disks are never written. A game plays
from working copies in <user data>/bardstale/disks, so the characters' progress
(written to the character disk by the game itself) survives restarts, and a MAME
save state taken on stop lets the next session resume exactly where it left off.
"""

from __future__ import annotations

import json
import os
import pathlib
import shutil
import subprocess
import tempfile
import threading
import time
from typing import Optional

from PIL import Image

from core import config

PKG_DIR = pathlib.Path(__file__).resolve().parent
PRISTINE_DISKS = PKG_DIR / "disks"
DISKS = {
    "boot": "bards_tale_boot.dsk",
    "character": "bards_tale_character.dsk",
    "dungeon": "bards_tale_dungeon.dsk",
}

DATA_DIR = config.USER_DATA_DIR / "bardstale"
WORK_DISKS = DATA_DIR / "disks"
MAME_DIR = DATA_DIR / "mame"        # cfg / nvram / save states — never the repo
SESSION_FILE = DATA_DIR / "session.json"
STATE_NAME = "omega7"
STATE_FILE = MAME_DIR / "sta" / "apple2e" / f"{STATE_NAME}.sta"

_shm = pathlib.Path("/dev/shm")
RUN_DIR = (_shm if _shm.is_dir() else pathlib.Path(tempfile.gettempdir())) / "omega7-bardstale"

_lock = threading.Lock()        # start/stop
_cmd_lock = threading.Lock()    # one writer for RUN_DIR/cmd
_proc: Optional[subprocess.Popen] = None
_frame_cache: tuple[int, Optional[Image.Image]] = (-1, None)
_drive0 = "boot"


def _child_setup() -> None:
    """In the MAME child before exec: lower its priority (the voice pipeline comes
    first) and have the kernel kill it if Omega-7 dies, since MAME ignores SIGTERM."""
    os.nice(10)
    try:
        import ctypes
        ctypes.CDLL("libc.so.6", use_errno=True).prctl(1, 9)  # PR_SET_PDEATHSIG, SIGKILL
    except Exception:
        pass


def _rompath() -> str:
    default = f"{pathlib.Path('~/.mame/roms').expanduser()};{PKG_DIR.parent / 'roms'}"
    return getattr(config, "BARDSTALE_ROMPATH", "") or default


def _load_session() -> dict:
    try:
        return json.loads(SESSION_FILE.read_text())
    except Exception:
        return {}


def save_session(**fields) -> None:
    """Merge fields into session.json (atomically)."""
    data = _load_session()
    data.update(fields)
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    tmp = SESSION_FILE.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, indent=2))
    os.replace(tmp, SESSION_FILE)


def session() -> dict:
    return _load_session()


def can_resume() -> bool:
    return STATE_FILE.exists() and all((WORK_DISKS / f).exists() for f in DISKS.values())


def missing_requirements() -> str:
    """Human-readable reason the game can't run, or '' when everything is present."""
    if not shutil.which("mame", path=f"/usr/games:{os.environ.get('PATH', '')}"):
        return "MAME is not installed."
    missing = [f for f in DISKS.values() if not (PRISTINE_DISKS / f).exists()]
    if missing:
        return f"Missing disk images: {', '.join(missing)}."
    dirs = [pathlib.Path(p).expanduser() for p in _rompath().split(";") if p]
    if not any((d / "apple2e.zip").exists() for d in dirs):
        return "The Apple IIe ROMs (apple2e.zip) are not installed."
    return ""


def start(resume: bool = True) -> bool:
    """Launch MAME. Resumes the saved game when there is one (and resume is set);
    otherwise starts fresh from pristine disk copies. Returns True once running."""
    global _proc, _drive0, _frame_cache
    with _lock:
        _stop_locked(save=False)
        problem = missing_requirements()
        if problem:
            print(f"[emulator] Cannot start: {problem}")
            return False

        resuming = resume and can_resume()
        if not resuming:
            WORK_DISKS.mkdir(parents=True, exist_ok=True)
            for f in DISKS.values():
                shutil.copyfile(PRISTINE_DISKS / f, WORK_DISKS / f)
            STATE_FILE.unlink(missing_ok=True)
            save_session(drive0="boot", turns=0, notes="", started=time.time())
        _drive0 = session().get("drive0", "boot") if resuming else "boot"
        if _drive0 not in DISKS:
            _drive0 = "boot"

        shutil.rmtree(RUN_DIR, ignore_errors=True)
        RUN_DIR.mkdir(parents=True)
        MAME_DIR.mkdir(parents=True, exist_ok=True)
        _frame_cache = (-1, None)

        cmd = [
            "mame", "apple2e",
            "-noreadconfig", "-rompath", _rompath(),
            "-video", "none", "-sound", "none",
            "-skip_gameinfo", "-noautosave", "-nomouse",
            "-cfg_directory", str(MAME_DIR / "cfg"),
            "-nvram_directory", str(MAME_DIR / "nvram"),
            "-state_directory", str(MAME_DIR / "sta"),
            "-snapshot_directory", str(MAME_DIR / "snap"),
            "-diff_directory", str(MAME_DIR / "diff"),
            "-input_directory", str(MAME_DIR / "inp"),
            "-comment_directory", str(MAME_DIR / "comments"),
            "-flop1", str(WORK_DISKS / DISKS[_drive0]),
            "-autoboot_script", str(PKG_DIR / "control.lua"),
        ]
        if resuming:
            cmd += ["-state", STATE_NAME]
        env = {**os.environ, "OMEGA7_BT_DIR": str(RUN_DIR),
               "PATH": f"/usr/games:{os.environ.get('PATH', '')}"}
        log = open(RUN_DIR / "mame.log", "wb")
        try:
            _proc = subprocess.Popen(cmd, stdout=log, stderr=subprocess.STDOUT, env=env,
                                     cwd=str(MAME_DIR), preexec_fn=_child_setup)
        except OSError as e:
            print(f"[emulator] Could not launch MAME: {e}")
            return False
        finally:
            log.close()

        deadline = time.monotonic() + 15
        while time.monotonic() < deadline:
            if _proc.poll() is not None:
                tail = (RUN_DIR / "mame.log").read_text(errors="replace")[-600:]
                print(f"[emulator] MAME exited during start (code {_proc.returncode}): {tail.strip()}")
                _proc = None
                return False
            if (RUN_DIR / "frame.info").exists():
                break
            time.sleep(0.2)
        print(f"[emulator] MAME apple2e running (pid {_proc.pid}), "
              f"{'resumed saved game' if resuming else 'new game'}, drive 1: {_drive0} disk")
        return True


def stop(save: bool = True) -> None:
    """Save the game (optionally) and shut MAME down cleanly so disk writes are flushed."""
    with _lock:
        _stop_locked(save)


def _stop_locked(save: bool) -> None:
    global _proc
    if _proc is None:
        return
    if _proc.poll() is None:
        if save:
            save_state()
        send("exit")  # a clean exit writes the disk images back
        try:
            _proc.wait(timeout=6)
        except subprocess.TimeoutExpired:
            _proc.kill()  # MAME ignores SIGTERM
            _proc.wait(timeout=4)
    _proc = None
    print("[emulator] Stopped.")


def is_running() -> bool:
    return _proc is not None and _proc.poll() is None


def send(line: str) -> bool:
    """Queue one command line for control.lua. Waits (briefly) for the previous one
    to be consumed, since the Lua side reads a single file."""
    if not is_running():
        return False
    path = RUN_DIR / "cmd"
    with _cmd_lock:
        deadline = time.monotonic() + 3
        while path.exists():
            if time.monotonic() > deadline or not is_running():
                print(f"[emulator] Command not consumed, dropping: {line[:40]}")
                return False
            time.sleep(0.03)
        tmp = RUN_DIR / "cmd.tmp"
        tmp.write_text(line + "\n")
        os.replace(tmp, path)
    return True


def type_keys(text: str) -> bool:
    """Type text on the Apple II keyboard ("\\r" = Return, "\\x1b" = Esc)."""
    return send("keys " + text.encode("latin-1", "replace").hex())


def insert_disk(name: str) -> bool:
    """Put the named disk ("boot", "character" or "dungeon") in drive 1."""
    global _drive0
    if name not in DISKS or not send(f"load 0 {WORK_DISKS / DISKS[name]}"):
        return False
    _drive0 = name
    save_session(drive0=name)
    return True


def current_disk() -> str:
    return _drive0


def turbo(on: bool) -> None:
    send("turbo on" if on else "turbo off")


def save_state() -> bool:
    """Write a MAME save state and remember which disk is in the drive."""
    before = STATE_FILE.stat().st_mtime if STATE_FILE.exists() else 0.0
    if not send(f"save {STATE_NAME}"):
        return False
    deadline = time.monotonic() + 4
    while time.monotonic() < deadline:
        if STATE_FILE.exists() and STATE_FILE.stat().st_mtime != before:
            save_session(drive0=_drive0, saved=time.time())
            return True
        time.sleep(0.1)
    print("[emulator] Save state did not complete.")
    return False


def frame_seq() -> int:
    """Sequence number of the latest screen picture (bumps only when it changes)."""
    try:
        return int((RUN_DIR / "frame.info").read_text().split()[0])
    except Exception:
        return -1


def frame() -> tuple[int, Optional[Image.Image]]:
    """(seq, picture) of the latest screen: RGB at MAME's native 560x192."""
    global _frame_cache
    try:
        seq, w, h = (int(v) for v in (RUN_DIR / "frame.info").read_text().split())
    except Exception:
        return -1, None
    if seq == _frame_cache[0]:
        return _frame_cache
    try:
        raw = (RUN_DIR / "frame").read_bytes()
        img = Image.frombuffer("RGBA", (w, h), raw, "raw", "BGRA", 0, 1).convert("RGB")
    except Exception:
        return _frame_cache
    _frame_cache = (seq, img)
    return _frame_cache


def wait_stable(quiet: float = 0.7, timeout: float = 6.0, stop: Optional[threading.Event] = None) -> bool:
    """Wait until the screen hasn't changed for `quiet` seconds. False on timeout
    (e.g. an animated title screen), which callers treat as "good enough"."""
    deadline = time.monotonic() + timeout
    seq, since = frame_seq(), time.monotonic()
    while time.monotonic() < deadline:
        if stop is not None and stop.is_set():
            return False
        time.sleep(0.1)
        now_seq = frame_seq()
        if now_seq != seq:
            seq, since = now_seq, time.monotonic()
        elif time.monotonic() - since >= quiet:
            return True
    return False
