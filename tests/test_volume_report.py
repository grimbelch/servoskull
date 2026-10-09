"""Reading the speaker volume back off the hardware.

Asked what its volume was, the skull could only say "this unit has no sensor that
reads its volume back to it" and quote the last value it had set — which is wrong
the moment the web remote, another process or a person at the mixer changes it
(run on the Pi: python -m pytest tests).
"""
import pytest

audio = pytest.importorskip("core.audio")  # needs sounddevice (run on the Pi)


@pytest.fixture
def linux_pactl(monkeypatch):
    """Pretend to be the unit: Linux, pactl present, one sink at a known level."""
    monkeypatch.setattr("sys.platform", "linux")
    monkeypatch.setattr("shutil.which", lambda name: "/usr/bin/pactl"
                        if name == "pactl" else None)
    monkeypatch.setattr(audio, "_volume_sink", lambda: "alsa_output.test")
    state = {}

    def at(sink_percent):
        state["pct"] = sink_percent
        monkeypatch.setattr(audio, "_sink_percent", lambda sink: state["pct"])
    state["at"] = at
    return state


def test_the_sinks_percent_is_converted_back_to_the_spoken_scale(linux_pactl):
    # The setter sends a spoken L as 100*sqrt(L/100), so a sink at 50% is 25 spoken.
    linux_pactl["at"](50)
    assert audio.get_system_volume() == 25
    linux_pactl["at"](100)
    assert audio.get_system_volume() == 100
    linux_pactl["at"](0)
    assert audio.get_system_volume() == 0


def test_a_sink_that_cannot_be_read_reads_as_unknown(linux_pactl):
    linux_pactl["at"](None)
    assert audio.get_system_volume() is None


def test_the_spoken_line_states_the_level(linux_pactl):
    linux_pactl["at"](50)
    assert audio.describe_volume() == "Volume is at 25 percent."


def test_an_unreadable_sink_says_so_and_falls_back_to_what_was_set(linux_pactl, monkeypatch):
    linux_pactl["at"](None)
    monkeypatch.setattr(audio, "saved_volume", lambda default=50: 30)
    line = audio.describe_volume()
    assert "cannot read" in line and "30 percent" in line


def test_it_reads_the_sink_the_setter_writes_to(monkeypatch):
    # The default sink is the echo-cancel filter, whose volume is ignored; reading
    # that one would report a number that has nothing to do with loudness.
    monkeypatch.setattr("sys.platform", "linux")
    monkeypatch.setattr("shutil.which", lambda name: "/usr/bin/pactl"
                        if name == "pactl" else None)
    asked = []
    monkeypatch.setattr(audio, "_volume_sink", lambda: "alsa_output.the_card")
    monkeypatch.setattr(audio, "_sink_percent", lambda sink: asked.append(sink) or 100)
    audio.get_system_volume()
    assert asked == ["alsa_output.the_card"]


def test_a_broken_reader_is_unknown_rather_than_an_exception(monkeypatch):
    monkeypatch.setattr("sys.platform", "linux")
    monkeypatch.setattr("shutil.which", lambda name: "/usr/bin/pactl"
                        if name == "pactl" else None)
    monkeypatch.setattr(audio, "_volume_sink", lambda: "x")

    def boom(sink):
        raise OSError("pactl is not having it")
    monkeypatch.setattr(audio, "_sink_percent", boom)
    assert audio.get_system_volume() is None


# ── where the voice goes ──────────────────────────────────────────────────────

def test_switching_to_bluetooth_with_nothing_connected_says_so(monkeypatch):
    """It used to set the pin to None -- the system default -- and report "Voice
    output switched to the Bluetooth speaker" with no speaker connected."""
    from core import config
    monkeypatch.setattr(audio, "get_pulseaudio_sinks", lambda: {"internal": "echo_cancel.sink"})
    monkeypatch.setattr(config, "VOICE_OUTPUT_DEVICE", "echo_cancel.sink")
    line = audio.set_voice_target("bluetooth")
    assert "No Bluetooth speaker is connected" in line
    assert config.VOICE_OUTPUT_DEVICE == "echo_cancel.sink"   # left where it was


def test_switching_to_bluetooth_works_when_one_is_connected(monkeypatch):
    from core import config
    monkeypatch.setattr(audio, "get_pulseaudio_sinks",
                        lambda: {"internal": "echo_cancel.sink",
                                 "bluetooth": "bluez_output.AA_BB.1"})
    monkeypatch.setattr(config, "VOICE_OUTPUT_DEVICE", "echo_cancel.sink")
    line = audio.set_voice_target("bluetooth")
    assert "switched to the Bluetooth speaker" in line
    assert config.VOICE_OUTPUT_DEVICE == "bluez_output.AA_BB.1"


def test_switching_back_to_internal_always_works(monkeypatch):
    from core import config
    monkeypatch.setattr(audio, "get_pulseaudio_sinks", lambda: {"internal": "echo_cancel.sink"})
    monkeypatch.setattr(audio, "get_internal_speaker_sink", lambda: "echo_cancel.sink")
    monkeypatch.setattr(config, "VOICE_OUTPUT_DEVICE", "bluez_output.AA_BB.1")
    audio.set_voice_target("internal")
    assert config.VOICE_OUTPUT_DEVICE == "echo_cancel.sink"
