"""Where system audio goes, in PipeWire terms.

Separate from BlueZ: connecting a speaker and sending audio to it are two
different systems, and conflating them is how audio ended up on the wrong device.
The reconciler reads these as facts and acts on the difference; nothing here waits
or retries, because waiting is the reconciler's business.
"""

from __future__ import annotations

import subprocess


def _pactl(*args: str, timeout: float = 5.0) -> str:
    return subprocess.run(["pactl", *args], capture_output=True, text=True,
                          timeout=timeout).stdout


def sink_for_mac(mac: str, sinks_output: str) -> str | None:
    """The sink belonging to `mac` in `pactl list short sinks` output, or None.

    Matches the address alone. A fallback of "the first line containing bluez"
    matches any Bluetooth sink at all, so with two speakers paired it sent audio to
    whichever pactl listed first -- and pactl lists by index, so usually the one
    connected earlier.
    """
    mac_under = mac.replace(":", "_").replace("-", "_").lower()
    for line in sinks_output.splitlines():
        parts = line.split()
        if len(parts) >= 2 and mac_under in parts[1].lower():
            return parts[1]
    return None


def list_sinks() -> str:
    try:
        return _pactl("list", "short", "sinks")
    except Exception as e:
        print(f"[bt] Could not list sinks: {e}")
        return ""


def current_sink_for(mac: str | None) -> str | None:
    """The sink for `mac` right now, or None if it has not appeared yet."""
    if not mac:
        return None
    return sink_for_mac(mac, list_sinks())


def default_sink() -> str | None:
    try:
        return _pactl("get-default-sink").strip() or None
    except Exception as e:
        print(f"[bt] Could not read the default sink: {e}")
        return None


def set_default_sink(name: str) -> bool:
    try:
        subprocess.run(["pactl", "set-default-sink", name],
                       capture_output=True, timeout=5, check=True)
        print(f"[bt] System audio default -> {name}")
        return True
    except Exception as e:
        print(f"[bt] Could not set the default sink to {name}: {e}")
        return False


def internal_sink() -> str | None:
    """Omega-7's own speaker: the echo-cancel sink when loaded, else the card.

    The echo-cancel one, not the raw USB one, so the canceller keeps its reference
    and the skull cannot hear itself.
    """
    from core import audio
    try:
        return audio.get_pulseaudio_sinks().get("internal") or None
    except Exception as e:
        print(f"[bt] Could not find the internal sink: {e}")
        return None


def pin_voice_to_internal() -> None:
    """Keep TTS and sound effects on the skull's own speaker, whatever is default.

    Both the connect and the disconnect path need this. The disconnect path used to
    set the pin to None and lean on the default sink having just been restored,
    which holds only while that restore succeeds.
    """
    from core import config
    sink = internal_sink()
    config.VOICE_OUTPUT_DEVICE = sink
    print(f"[bt] Voice pinned to the internal sink: {sink}")
