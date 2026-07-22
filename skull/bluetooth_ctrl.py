"""
Bluetooth speaker discovery and connection for Raspberry Pi.
Uses bluetoothctl subprocess — requires BlueZ (pre-installed on Pi OS).
Gracefully unavailable on non-Linux hosts.
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
    """Connect to a device by MAC address.

    Sets the BT device as the PulseAudio default sink so Spotify/system audio
    plays through it. Pins config.VOICE_OUTPUT_DEVICE to the pre-BT local device
    so TTS/SFX stay on Omega-7's own speaker.
    """
    if not is_supported():
        return False

    # Snapshot the local output device index BEFORE BT routing changes the default
    local_out = -1
    try:
        import sounddevice as _sd
        local_out = int(_sd.query_devices(kind="output")["index"])
    except Exception:
        pass

    try:
        proc = subprocess.Popen(
            ["bluetoothctl"],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
        )
        proc.stdin.write(f"power on\nagent on\ndefault-agent\nunblock {mac}\ntrust {mac}\npair {mac}\nconnect {mac}\n")
        proc.stdin.flush()
        time.sleep(10)
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
            _route_audio(mac, local_out)

        return success

    except Exception as e:
        print(f"[bluetooth] Connect error: {e}")
        return False


def _route_audio(mac: str, local_device_idx: int) -> None:
    """Route BT audio without disturbing TTS output.

    - Sets the BT device as the PulseAudio default sink so Spotify/system audio
      plays through it automatically.
    - Pins config.VOICE_OUTPUT_DEVICE to the pre-BT local device so TTS/SFX
      stay on Omega-7's own speaker regardless of the new default sink.
    """
    time.sleep(2)  # give the sink a moment to register

    mac_under = mac.replace(":", "_").lower()
    try:
        sinks = subprocess.run(
            ["pactl", "list", "short", "sinks"],
            capture_output=True, text=True, timeout=5,
        ).stdout
        sink_name = None
        for line in sinks.splitlines():
            line_lower = line.lower()
            if mac_under in line_lower or "bluez" in line_lower:
                sink_name = line.split()[1]
                break

        if sink_name:
            subprocess.run(
                ["pactl", "set-default-sink", sink_name],
                capture_output=True, timeout=5,
            )
            print(f"[bluetooth] System audio default → {sink_name}")
        else:
            print(f"[bluetooth] Sink for {mac} not found — PulseAudio default unchanged")

    except Exception as e:
        print(f"[bluetooth] Audio routing error: {e}")

    # Pin voice output to the pre-BT local device so TTS/SFX stay on Omega-7's speaker
    from skull import config
    if local_device_idx >= 0:
        config.VOICE_OUTPUT_DEVICE = local_device_idx
        print(f"[bluetooth] Voice pinned to local device {local_device_idx}")
