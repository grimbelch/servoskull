"""
Bluetooth speaker discovery and connection for Raspberry Pi.
Uses pexpect to drive interactive bluetoothctl with prompt synchronization and auto-agent authorization.
"""
from __future__ import annotations
import re
import subprocess
import time

_last_scan: list[dict] = []
PROMPT = r"\[.*?\][>#]"


def is_supported() -> bool:
    try:
        return subprocess.run(
            ["which", "bluetoothctl"], capture_output=True
        ).returncode == 0
    except Exception:
        return False


def scan(timeout: int = 8) -> list[dict]:
    """Scan for nearby Bluetooth devices using pexpect prompt synchronization.
    Caches results for bluetooth_connect.
    Returns list of {"name": str, "mac": str} dicts.
    """
    global _last_scan

    if not is_supported():
        print("[bluetooth] bluetoothctl not available")
        return []

    try:
        import pexpect
        child = pexpect.spawn("bluetoothctl", encoding="utf-8", timeout=15)
        
        # Wait for initial daemon connection & prompt
        child.expect(PROMPT)
        child.sendline("power on")
        child.expect(PROMPT)
        child.sendline("agent on")
        child.expect(PROMPT)
        child.sendline("default-agent")
        child.expect(PROMPT)

        child.sendline("scan on")
        devices_dict: dict[str, str] = {}

        t0 = time.time()
        while time.time() - t0 < timeout:
            try:
                idx = child.expect([r"Device ([0-9A-Fa-f:]{17})\s+(.+)", PROMPT, pexpect.TIMEOUT], timeout=1)
                if idx == 0:
                    mac = child.match.group(1).upper()
                    name = child.match.group(2).strip()
                    if name and not re.fullmatch(r"[0-9A-Fa-f:]{17}", name) and not name.startswith("RSSI:"):
                        devices_dict[mac] = name
            except Exception:
                pass

        child.sendline("scan off")
        child.expect(PROMPT)

        # Retrieve cached device list from bluetoothctl
        child.sendline("devices")
        try:
            child.expect(PROMPT, timeout=3)
            for line in child.before.splitlines():
                m = re.search(r"Device ([0-9A-Fa-f:]{17})\s+(.+)", line)
                if m:
                    mac = m.group(1).upper()
                    name = m.group(2).strip()
                    if name and not re.fullmatch(r"[0-9A-Fa-f:]{17}", name) and not name.startswith("RSSI:"):
                        devices_dict[mac] = name
        except Exception:
            pass

        child.sendline("quit")
        try:
            child.close()
        except Exception:
            pass

        devices = [{"name": name, "mac": mac} for mac, name in devices_dict.items()]
        _last_scan = devices
        print(f"[bluetooth] Discovered {len(devices)} device(s): {[d['name'] for d in devices]}")
        return devices

    except Exception as e:
        print(f"[bluetooth] Scan error: {e}")
        return []


def get_last_scan() -> list[dict]:
    return _last_scan


def connect(mac: str) -> bool:
    """Connect to a Bluetooth device by MAC address using interactive pexpect automation.

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
        import pexpect
        print(f"[bluetooth] Initiating interactive pairing sequence for {mac}...")
        child = pexpect.spawn("bluetoothctl", encoding="utf-8", timeout=20)
        
        # Wait for daemon ready
        child.expect(PROMPT)
        child.sendline("power on")
        child.expect(PROMPT)
        child.sendline("agent on")
        child.expect(PROMPT)
        child.sendline("default-agent")
        child.expect(PROMPT)

        # Unblock and trust device
        child.sendline(f"unblock {mac}")
        child.expect(PROMPT)
        child.sendline(f"trust {mac}")
        child.expect(PROMPT)

        # Attempt pairing with auto-confirmation loop
        print(f"[bluetooth] Sending pair command to {mac}...")
        child.sendline(f"pair {mac}")

        paired = False
        t0 = time.time()
        while time.time() - t0 < 15:
            try:
                idx = child.expect([
                    r"Paired: yes",
                    r"Pairing successful",
                    r"AlreadyExists",
                    r"Confirm passkey",
                    r"Authorize service",
                    r"Failed to pair",
                    PROMPT,
                    pexpect.TIMEOUT
                ], timeout=2)

                if idx in (0, 1, 2):
                    paired = True
                    print(f"[bluetooth] Pairing confirmed for {mac}")
                    break
                elif idx in (3, 4):
                    print(f"[bluetooth] Auto-confirming passkey/service authorization prompt...")
                    child.sendline("yes")
                elif idx == 5:
                    print(f"[bluetooth] Pairing error received for {mac}")
                    break
            except Exception:
                pass

        # Attempt connection
        print(f"[bluetooth] Sending connect command to {mac}...")
        child.sendline(f"connect {mac}")

        connected = False
        t0 = time.time()
        while time.time() - t0 < 15:
            try:
                idx = child.expect([
                    r"Connection successful",
                    r"Connected: yes",
                    r"Failed to connect",
                    PROMPT,
                    pexpect.TIMEOUT
                ], timeout=2)

                if idx in (0, 1):
                    connected = True
                    print(f"[bluetooth] Connection successful for {mac}!")
                    break
                elif idx == 2:
                    print(f"[bluetooth] Connection failed for {mac}")
                    break
            except Exception:
                pass

        child.sendline("quit")
        try:
            child.close()
        except Exception:
            pass

        if connected:
            _route_audio(mac, local_out)

        return connected

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

