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


# The echo canceller is a filter node: it takes the mic in and plays its reference
# out into a sink. The conf targets the USB card, but WirePlumber re-linked that
# output to the Bluetooth speaker when one connected -- so everything the skull said
# went through the canceller INTO the Craft Room, and the canceller's reference was
# a different device from its microphone, which quietly breaks the cancelling too.
CANCELLER_NODE = "echo-cancel-playback"


def card_sink(sinks_output: str = "") -> str | None:
    """The real sound card's sink: the one the canceller should be playing into."""
    out = sinks_output or list_sinks()
    for line in out.splitlines():
        parts = line.split()
        if len(parts) >= 2 and parts[1].startswith("alsa_output."):
            return parts[1]
    return None


def canceller_outputs(links_output: str) -> list[tuple[str, str]]:
    """(our output port, the port it feeds) for each link out of the canceller.

    Parses `pw-link -l`, where a link is a port line followed by indented
    "|-> target" lines.
    """
    pairs: list[tuple[str, str]] = []
    source = None
    for raw in links_output.splitlines():
        line = raw.rstrip()
        if not line:
            continue
        if not line.startswith((" ", "\t")):
            source = line.strip() if line.startswith(CANCELLER_NODE + ":") else None
            continue
        if source and "|->" in line:
            pairs.append((source, line.split("|->", 1)[1].strip()))
    return pairs


def _pw_link_list() -> str:
    try:
        return subprocess.run(["pw-link", "-l"], capture_output=True, text=True,
                              timeout=5).stdout
    except Exception as e:
        print(f"[bt] Could not list PipeWire links: {e}")
        return ""


def canceller_plays_into_card() -> bool | None:
    """True if the canceller feeds the sound card, False if elsewhere, None if unknown."""
    card = card_sink()
    pairs = canceller_outputs(_pw_link_list())
    if not card or not pairs:
        return None
    return all(t.startswith(card + ":") for _, t in pairs)


def restore_canceller_to_card() -> bool:
    """Put the canceller's output back on the sound card.

    Without this the skull's own voice follows the canceller to whatever sink
    WirePlumber moved it to, and the cancelling has the wrong reference.
    """
    card = card_sink()
    if not card:
        print("[bt] No sound-card sink found; leaving the canceller alone.")
        return False
    pairs = canceller_outputs(_pw_link_list())
    if not pairs:
        print("[bt] The echo canceller has no output links to correct.")
        return False
    moved = False
    for src, target in pairs:
        if target.startswith(card + ":"):
            continue
        port = src.split(":", 1)[1] if ":" in src else "output_FL"
        want = f"{card}:{port.replace('output_', 'playback_')}"
        try:
            subprocess.run(["pw-link", "-d", src, target],
                           capture_output=True, timeout=5)
            subprocess.run(["pw-link", src, want], capture_output=True, timeout=5,
                           check=True)
            print(f"[bt] Canceller output {src} moved from {target} back to {want}")
            moved = True
        except Exception as e:
            print(f"[bt] Could not move {src} back to the card: {e}")
            return False
    if not moved:
        print("[bt] The echo canceller was already playing into the sound card.")
    return True


def pin_voice_to_internal() -> None:
    """Keep TTS and sound effects on the skull's own speaker, whatever is default.

    Both the connect and the disconnect path need this. The disconnect path used to
    set the pin to None and lean on the default sink having just been restored,
    which holds only while that restore succeeds.
    """
    from core import config
    # The canceller first: pinning the voice to echo_cancel.sink only keeps it local
    # while that sink's own output is the sound card.
    restore_canceller_to_card()
    sink = internal_sink()
    if canceller_plays_into_card() is False:
        # Could not be put back, so name the card directly. The voice then bypasses
        # the canceller's reference, but barge-in listens to the raw microphone now
        # and the skull's own speech scores 0.02 there, so it will not rouse itself.
        sink = card_sink() or sink
        print("[bt] Canceller is not on the card; pinning the voice straight to it.")
    config.VOICE_OUTPUT_DEVICE = sink
    print(f"[bt] Voice pinned to: {sink}")
