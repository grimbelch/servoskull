"""Keep systemd's watchdog fed while the main thread is making progress.

The unit file sets WatchdogSec; systemd restarts the service if it hears nothing
for that long. A pinger thread sends WATCHDOG=1 every PING_EVERY seconds, but only
while beat() has been called within the last STALE_AFTER seconds. So a main
thread stuck in a PortAudio call or a deadlock stops the pings and the service is
restarted, while long but healthy work (a two-minute reply, an hour at idle)
keeps beating from inside playback, recording and the wake-word loop.

beat() is one float store, cheap enough to call per audio chunk. Without
NOTIFY_SOCKET (a manual run, or a unit without WatchdogSec) it is all a no-op.
"""

from __future__ import annotations

import os
import socket
import threading
import time

STALE_AFTER = 180.0   # seconds without a beat before pings stop
PING_EVERY = 30.0     # keep this well under the unit's WatchdogSec

_last_beat = time.monotonic()
_stalled_reported = False


def beat() -> None:
    """The main thread is alive and doing something."""
    global _last_beat
    _last_beat = time.monotonic()


def seconds_since_beat() -> float:
    return time.monotonic() - _last_beat


def _notify(message: bytes) -> bool:
    """Send one sd_notify(3) message; False if there is no socket or it failed."""
    addr = os.environ.get("NOTIFY_SOCKET")
    if not addr:
        return False
    if addr.startswith("@"):
        addr = "\0" + addr[1:]  # abstract namespace
    try:
        with socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM) as s:
            s.connect(addr)
            s.send(message)
        return True
    except OSError as e:
        print(f"[watchdog] notify failed: {e}")
        return False


def start() -> None:
    """Start pinging systemd. Call once the service is up."""
    if not os.environ.get("NOTIFY_SOCKET"):
        print("[watchdog] No NOTIFY_SOCKET (not under systemd, or no WatchdogSec) — pings disabled.")
        return
    beat()
    _notify(b"READY=1")
    threading.Thread(target=_loop, daemon=True, name="watchdog").start()
    print(f"[watchdog] Feeding systemd every {PING_EVERY:.0f}s while the main thread "
          f"beats within {STALE_AFTER:.0f}s.")


def _loop() -> None:
    global _stalled_reported
    while True:
        time.sleep(PING_EVERY)
        idle = seconds_since_beat()
        if idle < STALE_AFTER:
            _notify(b"WATCHDOG=1")
            _stalled_reported = False
        elif not _stalled_reported:
            _stalled_reported = True
            print(f"[watchdog] Main thread has made no progress for {idle:.0f}s — withholding "
                  "pings; systemd will restart the service.")
