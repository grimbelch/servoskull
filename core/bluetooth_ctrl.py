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


# Spoken ways of saying "every connected device".
ALL_TARGETS = ("all", "*", "", "everything", "every", "any")


def resolve_target(identifier: str, devices: list[dict]) -> str | None:
    """The MAC a spoken name or address refers to, or None if nothing matches.

    Pure, so the choice is testable. Callers must check for ALL_TARGETS first: a
    name this cannot resolve is a failed request, never an instruction to act on
    everything.
    """
    ident = (identifier or "").lower().strip()
    if not ident:
        return None
    for d in devices:
        if ident in d["name"].lower() or ident in d["mac"].lower():
            return d["mac"]
    return identifier.upper() if _is_mac(identifier) else None


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
        scanning = False
        send = None   # unbound if the first prompt never arrives
        try:
            child.expect(PROMPT)
    
            def send_cmd(cmd: str, t: float = 10.0) -> str:
                child.sendline(cmd)
                child.expect(re.escape(cmd), timeout=t)
                child.expect(PROMPT, timeout=t)
                return child.before
            send = send_cmd
    
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
            scanning = True
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
    
        finally:
            # Leaving the adapter scanning costs power and air time, so stop it
            # however the block above was left -- and do not let one failed
            # cleanup command skip the next.
            if send is not None and scanning:
                try:
                    send("scan off")
                except Exception as e:
                    print(f"[bluetooth] Could not stop the scan cleanly: {e}")
            if send is not None:
                try:
                    send("quit")
                except Exception:
                    pass
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

    try:
        import pexpect
        print(f"[bluetooth] Initiating interactive pairing/connection sequence for {mac}...")
        child = pexpect.spawn("bluetoothctl", encoding="utf-8", timeout=20)
        try:
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
                except Exception:
                    pass
                _route_audio(mac)
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
            except Exception:
                pass
        finally:
            try:
                child.close()
            except Exception:
                pass

        if connected:
            _route_audio(mac)

        return connected

    except Exception as e:
        print(f"[bluetooth] Connect error: {e}")
        return False


def disconnect(identifier: str = "all") -> bool:
    """Disconnect from a Bluetooth device by MAC, name, or disconnect all active devices."""
    if not is_supported():
        return False

    ident = identifier.lower().strip()
    target_mac = None
    if ident not in ALL_TARGETS:
        target_mac = resolve_target(identifier, get_last_scan() or scan(timeout=2))
        if target_mac is None:
            # Falling through to the "disconnect everything" branch below is how asking
            # for one speaker by a name we could not place silenced all of them.
            print(f"[bluetooth] Nothing matches '{identifier}'; no device disconnected. "
                  f"Say 'all' to disconnect every device.")
            return False

    try:
        import pexpect
        print(f"[bluetooth] Disconnecting Bluetooth device(s) (target: {identifier})...")
        child = pexpect.spawn("bluetoothctl", encoding="utf-8", timeout=15)
        try:
            child.expect(PROMPT)
    
            def send_cmd(cmd: str, t: float = 8.0) -> str:
                child.sendline(cmd)
                child.expect(re.escape(cmd), timeout=t)
                child.expect(PROMPT, timeout=t)
                return child.before
    
            def still_connected(mac: str) -> bool:
                try:
                    return "Connected: yes" in send_cmd(f"info {mac}")
                except Exception:
                    return False  # cannot tell; do not claim a failure we did not see

            send_cmd("power on")

            if target_mac:
                print(f"[bluetooth] Disconnecting {target_mac}...")
                send_cmd(f"disconnect {target_mac}")
                dropped = not still_connected(target_mac)
            else:
                dev_out = send_cmd("devices")
                attempted = 0
                dropped = True
                for line in dev_out.splitlines():
                    m = re.search(r"Device ([0-9A-Fa-f:]{17})", line)
                    if not m:
                        continue
                    mac = m.group(1).upper()
                    try:
                        if "Connected: yes" not in send_cmd(f"info {mac}"):
                            continue
                        print(f"[bluetooth] Disconnecting active device {mac}...")
                        send_cmd(f"disconnect {mac}")
                        attempted += 1
                        if still_connected(mac):
                            dropped = False
                    except Exception:
                        pass
                if attempted == 0:
                    print("[bluetooth] No device was connected.")

            try:
                send_cmd("quit")
            except Exception:
                pass
        finally:
            try:
                child.close()
            except Exception:
                pass

        if dropped:
            _restore_local_audio()
        else:
            print("[bluetooth] Still reports Connected: yes after the disconnect.")
        return dropped

    except Exception as e:
        print(f"[bluetooth] Disconnect error: {e}")
        return False


# The sink for a speaker appears a moment after the connection completes, so it is
# waited for rather than slept on, and never guessed at.
_SINK_WAIT_SECS = 6.0
_SINK_POLL_SECS = 0.25


def _bt_sink_for(mac: str, sinks_output: str) -> str | None:
    """The sink belonging to `mac` in `pactl list short sinks` output, or None.

    Matches the address alone. The previous fallback took the first line containing
    "bluez", which is any Bluetooth sink at all -- so connecting a second speaker
    while the first was still up sent the audio to whichever pactl listed first.
    """
    mac_under = mac.replace(":", "_").replace("-", "_").lower()
    for line in sinks_output.splitlines():
        parts = line.split()
        if len(parts) >= 2 and mac_under in parts[1].lower():
            return parts[1]
    return None


def _wait_for_bt_sink(mac: str, timeout: float | None = None) -> str | None:
    """Poll pactl until the sink for `mac` shows up, or give up and return None.

    The wait is read at call time, not bound as a default, so the constant above is
    the single place it lives.
    """
    deadline = time.time() + (_SINK_WAIT_SECS if timeout is None else timeout)
    while True:
        try:
            out = subprocess.run(
                ["pactl", "list", "short", "sinks"],
                capture_output=True, text=True, timeout=5,
            ).stdout
        except Exception as e:
            print(f"[bluetooth] Could not list sinks: {e}")
            return None
        sink = _bt_sink_for(mac, out)
        if sink:
            return sink
        if time.time() >= deadline:
            return None
        time.sleep(_SINK_POLL_SECS)


def _pin_voice_to_internal() -> None:
    """Keep TTS/SFX on Omega-7's own speaker, whatever the system default is.

    The echo-cancel sink when it is loaded, not the raw USB one, so the AEC keeps
    its reference and the skull cannot hear or wake itself. Both the connect and the
    disconnect path call this: the disconnect path used to set the pin to None and
    lean on the system default having just been restored, which is only correct
    while that restore succeeds.
    """
    from core import config, audio
    int_sink = audio.get_internal_speaker_sink()
    config.VOICE_OUTPUT_DEVICE = int_sink
    print(f"[bluetooth] Voice pinned to internal speaker sink: {int_sink}")


def _route_audio(mac: str) -> None:
    """Route BT audio without disturbing TTS output.

    - Sets the BT device as the PulseAudio default sink so Spotify/system audio
      plays through it automatically.
    - Pins config.VOICE_OUTPUT_DEVICE to the local speaker so TTS/SFX stay on
      Omega-7's own speaker by default. That's the echo-cancel sink when present
      (not the raw USB sink), so the AEC keeps its reference and the skull can't
      hear/wake itself. It is resolved here rather than snapshotted before the
      connection: connect() used to query sounddevice for the pre-BT output index
      and pass it in, and this function never read it.
    """
    try:
        sink_name = _wait_for_bt_sink(mac)
        if sink_name:
            subprocess.run(
                ["pactl", "set-default-sink", sink_name],
                capture_output=True, timeout=5,
            )
            print(f"[bluetooth] System audio default → {sink_name}")
        else:
            print(f"[bluetooth] No sink for {mac} after {_SINK_WAIT_SECS:.0f}s — "
                  f"system default left alone rather than guessed at")
    except Exception as e:
        print(f"[bluetooth] Audio routing error: {e}")

    _pin_voice_to_internal()


def _restore_local_audio() -> None:
    """Restore default PulseAudio/PipeWire sink to Omega-7's local speaker.

    Prefers the echo-cancel sink over the raw USB/ALSA card: restoring the raw sink
    as the default would bypass the AEC, so the skull's voice would reach the mic
    uncancelled and could trigger its own wake word.
    """
    from core import audio
    try:
        s_name = audio.get_pulseaudio_sinks().get("internal")
        if s_name:
            subprocess.run(["pactl", "set-default-sink", s_name], capture_output=True, timeout=5)
            print(f"[bluetooth] Restored system default sink → {s_name}")
        else:
            print("[bluetooth] No local sink found — PulseAudio default unchanged")
    except Exception as e:
        print(f"[bluetooth] Restore audio error: {e}")

    _pin_voice_to_internal()

