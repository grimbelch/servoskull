"""core.watchdog: beats and sd_notify messages (run: python -m pytest tests)."""

import os
import socket
import tempfile
import time



from core import watchdog


def test_beat_resets_the_idle_clock(monkeypatch):
    monkeypatch.setattr(watchdog, "_last_beat", time.monotonic() - 500.0)
    assert watchdog.seconds_since_beat() > 400
    watchdog.beat()
    assert watchdog.seconds_since_beat() < 1.0


def test_notify_is_a_noop_without_a_socket(monkeypatch):
    monkeypatch.delenv("NOTIFY_SOCKET", raising=False)
    assert watchdog._notify(b"WATCHDOG=1") is False


def test_notify_sends_the_message_to_the_socket(monkeypatch):
    # A short path: AF_UNIX paths are capped at ~104 bytes on macOS and pytest's
    # tmp_path is longer than that.
    with tempfile.TemporaryDirectory(dir="/tmp") as d:
        path = os.path.join(d, "notify.sock")
        with socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM) as server:
            server.bind(path)
            server.settimeout(2.0)
            monkeypatch.setenv("NOTIFY_SOCKET", path)
            assert watchdog._notify(b"WATCHDOG=1") is True
            assert server.recv(64) == b"WATCHDOG=1"


def test_notify_reports_a_dead_socket(monkeypatch, tmp_path):
    monkeypatch.setenv("NOTIFY_SOCKET", str(tmp_path / "missing.sock"))
    assert watchdog._notify(b"WATCHDOG=1") is False
