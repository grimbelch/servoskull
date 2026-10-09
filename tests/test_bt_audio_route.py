"""Keeping the skull's voice on the skull's own speaker.

The echo canceller is a filter node that plays its reference out into a sink. The
conf targets the USB card, but WirePlumber re-linked that output to a Bluetooth
speaker when one connected -- so everything the skull said went through the
canceller INTO the Craft Room, and the canceller's reference became a different
device from its microphone (run: python -m pytest tests).
"""
from core.bt import audio_route as ar

CARD = "alsa_output.usb-C-Media_Electronics_Inc._USB_Audio_Device-00.analog-stereo"
BT = "bluez_output.EC_81_93_68_CF_68.1"

SINKS = f"""\
0\techo_cancel.sink\tPipeWire\tfloat32le 2ch 48000Hz\tIDLE
1\t{CARD}\tPipeWire\ts16le 2ch 48000Hz\tIDLE
2\t{BT}\tPipeWire\ts16le 2ch 48000Hz\tIDLE
"""

# What the unit actually printed: the canceller feeding the Bluetooth speaker.
LINKS_WRONG = f"""\
echo-cancel-playback:output_FL
  |-> {BT}:playback_FL
echo-cancel-playback:output_FR
  |-> {BT}:playback_FR
alsa_input.usb-C-Media:capture_MONO
  |<- echo_cancel.source:capture_FL
"""

LINKS_RIGHT = f"""\
echo-cancel-playback:output_FL
  |-> {CARD}:playback_FL
echo-cancel-playback:output_FR
  |-> {CARD}:playback_FR
"""


def test_the_card_sink_is_found_among_the_others():
    assert ar.card_sink(SINKS) == CARD


def test_no_card_sink_is_none():
    assert ar.card_sink("0\techo_cancel.sink\tPipeWire\n") is None


def test_the_cancellers_outputs_are_read_off_the_graph():
    pairs = ar.canceller_outputs(LINKS_WRONG)
    assert pairs == [("echo-cancel-playback:output_FL", f"{BT}:playback_FL"),
                     ("echo-cancel-playback:output_FR", f"{BT}:playback_FR")]


def test_links_belonging_to_other_nodes_are_ignored():
    # The capture side and anything else in the graph must not be touched.
    pairs = ar.canceller_outputs(LINKS_WRONG)
    assert all(src.startswith("echo-cancel-playback:") for src, _ in pairs)


def test_an_empty_graph_yields_nothing():
    assert ar.canceller_outputs("") == []


def test_it_can_tell_where_the_canceller_is_playing(monkeypatch):
    monkeypatch.setattr(ar, "list_sinks", lambda: SINKS)
    monkeypatch.setattr(ar, "_pw_link_list", lambda: LINKS_WRONG)
    assert ar.canceller_plays_into_card() is False
    monkeypatch.setattr(ar, "_pw_link_list", lambda: LINKS_RIGHT)
    assert ar.canceller_plays_into_card() is True


def test_an_unknown_graph_is_unknown_rather_than_wrong(monkeypatch):
    monkeypatch.setattr(ar, "list_sinks", lambda: SINKS)
    monkeypatch.setattr(ar, "_pw_link_list", lambda: "")
    assert ar.canceller_plays_into_card() is None


def test_restoring_moves_each_misrouted_port_back(monkeypatch):
    monkeypatch.setattr(ar, "list_sinks", lambda: SINKS)
    monkeypatch.setattr(ar, "_pw_link_list", lambda: LINKS_WRONG)
    calls = []

    class Done:
        returncode = 0

    def run(cmd, **kw):
        calls.append(cmd)
        return Done()
    monkeypatch.setattr(ar.subprocess, "run", run)
    assert ar.restore_canceller_to_card() is True
    removed = [c for c in calls if c[:2] == ["pw-link", "-d"]]
    added = [c for c in calls if c[:2] != ["pw-link", "-d"]]
    assert [c[3] for c in removed] == [f"{BT}:playback_FL", f"{BT}:playback_FR"]
    assert [c[2] for c in added] == [f"{CARD}:playback_FL", f"{CARD}:playback_FR"]


def test_a_correctly_routed_canceller_is_left_alone(monkeypatch):
    monkeypatch.setattr(ar, "list_sinks", lambda: SINKS)
    monkeypatch.setattr(ar, "_pw_link_list", lambda: LINKS_RIGHT)
    calls = []
    monkeypatch.setattr(ar.subprocess, "run",
                        lambda cmd, **kw: calls.append(cmd))
    assert ar.restore_canceller_to_card() is True
    assert calls == []


def test_a_refused_relink_is_reported_not_swallowed(monkeypatch):
    monkeypatch.setattr(ar, "list_sinks", lambda: SINKS)
    monkeypatch.setattr(ar, "_pw_link_list", lambda: LINKS_WRONG)

    def boom(cmd, **kw):
        if cmd[:2] != ["pw-link", "-d"]:
            raise RuntimeError("pw-link refused")
        return None
    monkeypatch.setattr(ar.subprocess, "run", boom)
    assert ar.restore_canceller_to_card() is False


def test_the_voice_falls_back_to_the_card_when_the_canceller_cannot_be_moved(monkeypatch):
    from core import config
    monkeypatch.setattr(ar, "restore_canceller_to_card", lambda: False)
    monkeypatch.setattr(ar, "canceller_plays_into_card", lambda: False)
    monkeypatch.setattr(ar, "internal_sink", lambda: "echo_cancel.sink")
    monkeypatch.setattr(ar, "card_sink", lambda sinks_output="": CARD)
    monkeypatch.setattr(config, "VOICE_OUTPUT_DEVICE", None)
    ar.pin_voice_to_internal()
    # Pinning to echo_cancel.sink would have sent the voice to the Bluetooth speaker.
    assert config.VOICE_OUTPUT_DEVICE == CARD


def test_the_voice_uses_the_canceller_when_it_is_correctly_routed(monkeypatch):
    from core import config
    monkeypatch.setattr(ar, "restore_canceller_to_card", lambda: True)
    monkeypatch.setattr(ar, "canceller_plays_into_card", lambda: True)
    monkeypatch.setattr(ar, "internal_sink", lambda: "echo_cancel.sink")
    monkeypatch.setattr(config, "VOICE_OUTPUT_DEVICE", None)
    ar.pin_voice_to_internal()
    assert config.VOICE_OUTPUT_DEVICE == "echo_cancel.sink"
