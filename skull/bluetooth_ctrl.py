"""
Bluetooth speaker discovery and connection for Raspberry Pi.
Uses bluetoothctl subprocess — requires BlueZ (pre-installed on Pi OS).
Gracefully unavailable on Mac/Windows emulator.
"""
from __future__ import annotations
import re
import subprocess
import time

_last_scan: list[dict] = []


def is_supported() -> bool:
    try:
        return subprocess.run(
            ["which", "bluetoothctl"], capture_output=True
        ).returncode == 0
    except Exception:
        return False


def scan(timeout: int = 8) -> list[dict]:
    """Scan for nearby Bluetooth devices. Caches results for bluetooth_connect.
    Returns list of {"name": str, "mac": str} dicts.
    Takes ~timeout seconds to complete.
    """
    global _last_scan

    if not is_supported():
        print("[bluetooth] bluetoothctl not available")
        return []

    try:
        proc = subprocess.Popen(
            ["bluetoothctl"],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
        )
        proc.stdin.write("power on\nscan on\n")
        proc.stdin.flush()
        time.sleep(timeout)
        proc.stdin.write("scan off\ndevices\nquit\n")
        proc.stdin.flush()

        try:
            stdout, _ = proc.communicate(timeout=10)
        except subprocess.TimeoutExpired:
            proc.kill()
            stdout, _ = proc.communicate()

        devices: list[dict] = []
        seen: set[str] = set()
        for line in stdout.splitlines():
            m = re.search(r"Device ([0-9A-Fa-f:]{17})\s+(.+)", line)
            if not m:
                continue
            mac = m.group(1).upper()
            name = m.group(2).strip()
            # Skip unnamed entries and entries whose name is just the MAC
            if mac in seen or not name or re.fullmatch(r"[0-9A-Fa-f:]{17}", name):
                continue
            seen.add(mac)
            devices.append({"name": name, "mac": mac})

        _last_scan = devices
        return devices

    except Exception as e:
        print(f"[bluetooth] Scan error: {e}")
        return []


def get_last_scan() -> list[dict]:
    return _last_scan


def connect(mac: str) -> bool:
    """Connect to a device by MAC address and route Pi audio through it."""
    if not is_supported():
        return False

    try:
        proc = subprocess.Popen(
            ["bluetoothctl"],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
        )
        proc.stdin.write(f"power on\nconnect {mac}\n")
        proc.stdin.flush()
        time.sleep(8)
        proc.stdin.write("quit\n")
        proc.stdin.flush()

        try:
            stdout, _ = proc.communicate(timeout=15)
        except subprocess.TimeoutExpired:
            proc.kill()
            stdout, _ = proc.communicate()

        success = (
            "Connection successful" in stdout
            or "Connected: yes" in stdout
        )

        if success:
            _route_audio(mac)

        return success

    except Exception as e:
        print(f"[bluetooth] Connect error: {e}")
        return False


def _route_audio(mac: str) -> None:
    """Set connected BT device as PulseAudio/PipeWire default sink."""
    time.sleep(2)  # give the sink a moment to register

    # Try to find the bluez sink by MAC
    mac_under = mac.replace(":", "_")
    try:
        sinks = subprocess.run(
            ["pactl", "list", "short", "sinks"],
            capture_output=True, text=True, timeout=5,
        ).stdout
        sink_name = None
        for line in sinks.splitlines():
            if mac_under in line or "bluez" in line.lower():
                sink_name = line.split()[1]
                break

        if sink_name:
            subprocess.run(
                ["pactl", "set-default-sink", sink_name],
                capture_output=True, timeout=5,
            )
            # Switch runtime output to system default so sounddevice picks it up
            from skull import config
            config.AUDIO_OUTPUT_DEVICE = -1
            print(f"[bluetooth] Audio routed to {sink_name}")
        else:
            print(f"[bluetooth] Sink for {mac} not found — audio routing unchanged")

    except Exception as e:
        print(f"[bluetooth] Audio routing error: {e}")
