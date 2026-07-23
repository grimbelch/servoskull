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


def _clean_name(s: str) -> str:
    """Strip ANSI color sequences and trailing prompt lines from device names."""
    clean = re.sub(r"\x1b\[[0-9;]*[a-zA-Z]", "", s)
    return clean.splitlines()[0].strip()


def _is_mac(s: str) -> bool:
    """Check if string is a raw MAC address formatted with colons or dashes."""
    return bool(re.fullmatch(r"[0-9A-Fa-f]{2}([:\-][0-9A-Fa-f]{2}){5}", s.strip()))


def scan(timeout: int = 6) -> list[dict]:
    """Scan for nearby Bluetooth devices using pexpect prompt synchronization.
    Includes both active scan discoveries and cached known/paired devices.
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
        child.expect(PROMPT)

        def send_cmd(cmd: str, t: float = 10.0) -> str:
            child.sendline(cmd)
            child.expect(re.escape(cmd), timeout=t)
            child.expect(PROMPT, timeout=t)
            return child.before

        send_cmd("power on")
        send_cmd("agent on")
        send_cmd("default-agent")

        devices_dict: dict[str, str] = {}

        # 1. Fetch existing known/paired devices from bluetoothctl
        dev_out = send_cmd("devices")
        for line in dev_out.splitlines():
            m = re.search(r"Device ([0-9A-Fa-f:]{17})\s+(.+)", line)
            if m:
                mac = m.group(1).upper()
                name = _clean_name(m.group(2))
                if name and not _is_mac(name) and not name.startswith("RSSI:"):
                    devices_dict[mac] = name

        # 2. Perform live RF scan
        child.sendline("scan on")
        t0 = time.time()
        while time.time() - t0 < timeout:
            try:
                idx = child.expect([r"Device ([0-9A-Fa-f:]{17})\s+(.+)", pexpect.TIMEOUT], timeout=1)
                if idx == 0:
                    mac = child.match.group(1).upper()
                    name = _clean_name(child.match.group(2))
                    if name and not _is_mac(name) and not name.startswith("RSSI:"):
                        devices_dict[mac] = name
            except Exception:
                pass

        send_cmd("scan off")
        send_cmd("quit")
        try:
            child.close()
        except Exception:
            pass

        devices = [{"name": name, "mac": mac} for mac, name in devices_dict.items()]
        _last_scan = devices
        print(f"[bluetooth] Discovered/cached {len(devices)} device(s): {[d['name'] for d in devices]}")
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
        print(f"[bluetooth] Initiating interactive pairing/connection sequence for {mac}...")
        child = pexpect.spawn("bluetoothctl", encoding="utf-8", timeout=20)
        child.expect(PROMPT)

        def send_cmd(cmd: str, t: float = 10.0) -> str:
            child.sendline(cmd)
            child.expect(re.escape(cmd), timeout=t)
            child.expect(PROMPT, timeout=t)
            return child.before

        def is_connected_check() -> bool:
            try:
                info_out = send_cmd(f"info {mac}")
                return "Connected: yes" in info_out
            except Exception:
                return False

        send_cmd("power on")
        send_cmd("agent on")
        send_cmd("default-agent")

        # Fast path: check if already connected
        if is_connected_check():
            print(f"[bluetooth] Device {mac} is already connected!")
            try:
                send_cmd("quit")
                child.close()
            except Exception:
                pass
            _route_audio(mac, local_out)
            return True

        # Unblock and trust device
        send_cmd(f"unblock {mac}")
        send_cmd(f"trust {mac}")

        # Attempt pairing with auto-confirmation loop
        print(f"[bluetooth] Sending pair command to {mac}...")
        child.sendline(f"pair {mac}")
        try:
            p_idx = child.expect([
                r"Paired: yes",
                r"Pairing successful",
                r"AlreadyExists",
                r"Confirm passkey",
                r"Authorize service",
                r"Failed to pair"
            ], timeout=6)
            if p_idx in (3, 4):
                print("[bluetooth] Auto-confirming passkey/service authorization prompt...")
                child.sendline("yes")
        except Exception as e:
            print(f"[bluetooth] Pair status note: {e}")

        # Wait for prompt after pair command finishes
        try:
            child.expect(PROMPT, timeout=5)
        except Exception:
            pass

        # Attempt connection
        print(f"[bluetooth] Sending connect command to {mac}...")
        child.sendline(f"connect {mac}")
        try:
            child.expect(PROMPT, timeout=8)
        except Exception:
            pass

        connected = is_connected_check()
        print(f"[bluetooth] Final connection status for {mac}: {connected}")

        try:
            send_cmd("quit")
            child.close()
        except Exception:
            pass

        if connected:
            _route_audio(mac, local_out)

        return connected

    except Exception as e:
        print(f"[bluetooth] Connect error: {e}")
        return False


def disconnect(identifier: str = "all") -> bool:
    """Disconnect from a Bluetooth device by MAC, name, or disconnect all active devices."""
    if not is_supported():
        return False

    target_mac = None
    ident = identifier.lower().strip()
    if ident not in ("all", "*", "", "everything"):
        devices = get_last_scan() or scan(timeout=2)
        for d in devices:
            if ident in d["name"].lower() or ident in d["mac"].lower():
                target_mac = d["mac"]
                break
        if not target_mac and _is_mac(identifier):
            target_mac = identifier.upper()

    try:
        import pexpect
        print(f"[bluetooth] Disconnecting Bluetooth device(s) (target: {identifier})...")
        child = pexpect.spawn("bluetoothctl", encoding="utf-8", timeout=15)
        child.expect(PROMPT)

        def send_cmd(cmd: str, t: float = 8.0) -> str:
            child.sendline(cmd)
            child.expect(re.escape(cmd), timeout=t)
            child.expect(PROMPT, timeout=t)
            return child.before

        send_cmd("power on")

        if target_mac:
            print(f"[bluetooth] Disconnecting {target_mac}...")
            send_cmd(f"disconnect {target_mac}")
        else:
            dev_out = send_cmd("devices")
            for line in dev_out.splitlines():
                m = re.search(r"Device ([0-9A-Fa-f:]{17})", line)
                if m:
                    mac = m.group(1).upper()
                    try:
                        info_out = send_cmd(f"info {mac}")
                        if "Connected: yes" in info_out:
                            print(f"[bluetooth] Disconnecting active device {mac}...")
                            send_cmd(f"disconnect {mac}")
                    except Exception:
                        pass

        try:
            send_cmd("quit")
            child.close()
        except Exception:
            pass

        _restore_local_audio()
        return True

    except Exception as e:
        print(f"[bluetooth] Disconnect error: {e}")
        return False


def _route_audio(mac: str, local_device_idx: int = None) -> None:
    """Route BT audio without disturbing TTS output.

    - Sets the BT device as the PulseAudio default sink so Spotify/system audio
      plays through it automatically.
    - Pins config.VOICE_OUTPUT_DEVICE to the local hardware output device so TTS/SFX
      stay on Omega-7's own speaker by default.
    """
    time.sleep(1)  # give the sink a moment to register

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

    # Pin voice output explicitly to Omega-7's local hardware speaker
    from skull import config, audio
    hw_idx = audio.find_local_hardware_output_device()
    if hw_idx is not None:
        config.VOICE_OUTPUT_DEVICE = hw_idx
        print(f"[bluetooth] Voice pinned to local hardware device {hw_idx}")


def _restore_local_audio() -> None:
    """Restore default PulseAudio/PipeWire sink to local hardware audio card."""
    try:
        sinks = subprocess.run(
            ["pactl", "list", "short", "sinks"],
            capture_output=True, text=True, timeout=5
        ).stdout
        for line in sinks.splitlines():
            parts = line.split()
            if len(parts) >= 2:
                s_name = parts[1]
                if ("usb" in s_name.lower() or "alsa" in s_name.lower()) and "bluez" not in s_name.lower():
                    subprocess.run(["pactl", "set-default-sink", s_name], capture_output=True, timeout=5)
                    print(f"[bluetooth] Restored system default sink → {s_name}")
                    break
    except Exception as e:
        print(f"[bluetooth] Restore audio error: {e}")

    from skull import config
    config.VOICE_OUTPUT_DEVICE = None

