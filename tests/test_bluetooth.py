"""Choosing a Bluetooth target, and reporting what actually happened.

Asking to disconnect one speaker by a name that could not be resolved used to fall
through to the branch that disconnects every connected device, and disconnect()
returned True whenever no exception was raised — so the skull reported success it
had never checked (run: python -m pytest tests).
"""
import sys
import types

import pytest

from core import bluetooth_ctrl as bt

DEVICES = [
    {"name": "JBL Flip 6", "mac": "AA:BB:CC:DD:EE:01"},
    {"name": "Kitchen Nest", "mac": "AA:BB:CC:DD:EE:02"},
]


# ── choosing a target ─────────────────────────────────────────────────────────

def test_a_name_resolves_to_its_address():
    assert bt.resolve_target("jbl", DEVICES) == "AA:BB:CC:DD:EE:01"
    assert bt.resolve_target("Kitchen", DEVICES) == "AA:BB:CC:DD:EE:02"
    assert bt.resolve_target("flip 6", DEVICES) == "AA:BB:CC:DD:EE:01"


def test_a_raw_address_is_accepted_even_when_unknown():
    assert bt.resolve_target("aa:bb:cc:dd:ee:09", []) == "AA:BB:CC:DD:EE:09"


def test_a_name_that_matches_nothing_resolves_to_nothing():
    assert bt.resolve_target("sonos", DEVICES) is None
    assert bt.resolve_target("", DEVICES) is None


def test_the_words_meaning_everything_are_not_device_names():
    # disconnect() checks these before resolving, so they must stay out of the names.
    for word in bt.ALL_TARGETS:
        assert word not in [d["name"].lower() for d in DEVICES]


# ── a fake bluetoothctl ───────────────────────────────────────────────────────

class _FakeChild:
    """Enough of a pexpect child to drive bluetooth_ctrl's send_cmd loop."""

    def __init__(self, connected):
        self.connected = dict(connected)   # mac -> bool
        self.before = ""
        self.sent = []
        self.closed = False

    def sendline(self, cmd):
        self.sent.append(cmd)
        if cmd == getattr(self, "raise_on", None):
            raise RuntimeError(f"bluetoothctl refused {cmd!r}")
        if cmd == "devices":
            self.before = "\n".join(f"Device {m} Speaker" for m in self.connected)
        elif cmd.startswith("info "):
            mac = cmd.split()[1]
            self.before = f"Connected: {'yes' if self.connected.get(mac) else 'no'}"
        elif cmd.startswith("disconnect "):
            mac = cmd.split()[1]
            if self.connected.get(mac) and not getattr(self, "refuse", False):
                self.connected[mac] = False
            self.before = ""
        else:
            self.before = ""

    def expect(self, pattern, timeout=None):
        return 0

    def close(self):
        self.closed = True


@pytest.fixture
def fake_bt(monkeypatch):
    """Install a fake pexpect and report the child that bluetooth_ctrl drove."""
    made = {}

    def make(connected, refuse=False):
        child = _FakeChild(connected)
        child.refuse = refuse
        made["child"] = child
        fake = types.ModuleType("pexpect")
        fake.spawn = lambda *a, **k: child
        fake.TIMEOUT = type("TIMEOUT", (Exception,), {})
        monkeypatch.setitem(sys.modules, "pexpect", fake)
        monkeypatch.setattr(bt, "is_supported", lambda: True)
        monkeypatch.setattr(bt, "_restore_local_audio", lambda: made.__setitem__("restored", True))
        return child

    made["make"] = make
    return made


# ── disconnecting ─────────────────────────────────────────────────────────────

def test_an_unresolvable_name_disconnects_nothing(fake_bt, monkeypatch):
    child = fake_bt["make"]({"AA:BB:CC:DD:EE:01": True})
    monkeypatch.setattr(bt, "get_last_scan", lambda: [])
    monkeypatch.setattr(bt, "scan", lambda timeout=2: [])
    assert bt.disconnect("the sonos") is False
    # It must not have reached bluetoothctl at all, let alone dropped the JBL.
    assert child.sent == []
    assert child.connected["AA:BB:CC:DD:EE:01"] is True
    assert "restored" not in fake_bt


def test_a_named_device_is_the_only_one_dropped(fake_bt, monkeypatch):
    child = fake_bt["make"]({"AA:BB:CC:DD:EE:01": True, "AA:BB:CC:DD:EE:02": True})
    monkeypatch.setattr(bt, "get_last_scan", lambda: DEVICES)
    assert bt.disconnect("jbl") is True
    assert child.connected == {"AA:BB:CC:DD:EE:01": False, "AA:BB:CC:DD:EE:02": True}
    assert fake_bt.get("restored") is True


def test_all_drops_every_connected_device(fake_bt):
    child = fake_bt["make"]({"AA:BB:CC:DD:EE:01": True, "AA:BB:CC:DD:EE:02": True})
    assert bt.disconnect("all") is True
    assert set(child.connected.values()) == {False}


def test_a_device_that_stays_connected_is_reported_as_a_failure(fake_bt, monkeypatch):
    child = fake_bt["make"]({"AA:BB:CC:DD:EE:01": True}, refuse=True)
    monkeypatch.setattr(bt, "get_last_scan", lambda: DEVICES)
    assert bt.disconnect("jbl") is False
    assert child.connected["AA:BB:CC:DD:EE:01"] is True
    # Local audio must not be restored while the speaker still holds the connection.
    assert "restored" not in fake_bt


def test_disconnecting_when_nothing_is_connected_is_not_a_failure(fake_bt):
    fake_bt["make"]({"AA:BB:CC:DD:EE:01": False})
    assert bt.disconnect("all") is True


def test_the_child_is_always_closed(fake_bt):
    child = fake_bt["make"]({"AA:BB:CC:DD:EE:01": True})
    bt.disconnect("all")
    assert child.closed is True


# ── routing ───────────────────────────────────────────────────────────────────

def test_route_audio_takes_only_the_address():
    # connect() used to snapshot the pre-BT output index and pass it here, where it
    # was never read; the signature should no longer invite that.
    import inspect
    assert list(inspect.signature(bt._route_audio).parameters) == ["mac"]


# ── finding the right sink ────────────────────────────────────────────────────

SINKS = """\
0\talsa_output.usb-C-Media_Electronics_Inc._USB_Audio_Device-00.analog-stereo\tPipeWire\ts16le 2ch 48000Hz\tIDLE
1\techo_cancel.sink\tPipeWire\tfloat32le 2ch 48000Hz\tIDLE
2\tbluez_output.AA_BB_CC_DD_EE_02.1\tPipeWire\ts16le 2ch 48000Hz\tIDLE
3\tbluez_output.AA_BB_CC_DD_EE_01.1\tPipeWire\ts16le 2ch 48000Hz\tIDLE
"""


def test_the_sink_is_matched_by_address_not_by_being_bluetooth():
    # Both speakers are connected; the first bluez line listed is the other one.
    assert bt._bt_sink_for("AA:BB:CC:DD:EE:01", SINKS) == "bluez_output.AA_BB_CC_DD_EE_01.1"
    assert bt._bt_sink_for("AA:BB:CC:DD:EE:02", SINKS) == "bluez_output.AA_BB_CC_DD_EE_02.1"


def test_an_absent_speaker_matches_no_sink():
    # It must not fall back to any other Bluetooth sink.
    assert bt._bt_sink_for("AA:BB:CC:DD:EE:09", SINKS) is None
    assert bt._bt_sink_for("AA:BB:CC:DD:EE:01", "") is None


def test_dashed_addresses_match_too():
    assert bt._bt_sink_for("aa-bb-cc-dd-ee-01", SINKS) == "bluez_output.AA_BB_CC_DD_EE_01.1"


@pytest.fixture
def pactl(monkeypatch):
    """Record pactl invocations and serve a scripted sink list."""
    calls = []
    state = {"sinks": SINKS}

    class _Done:
        def __init__(self, out):
            self.stdout = out

    def run(cmd, **kw):
        calls.append(cmd)
        if cmd[:3] == ["pactl", "list", "short"]:
            return _Done(state["sinks"])
        return _Done("")

    monkeypatch.setattr(bt.subprocess, "run", run)
    monkeypatch.setattr(bt.time, "sleep", lambda s: None)
    monkeypatch.setattr(bt, "_pin_voice_to_internal", lambda: calls.append(["pinned"]))
    return {"calls": calls, "state": state}


def test_routing_sets_the_default_to_the_right_speaker(pactl):
    bt._route_audio("AA:BB:CC:DD:EE:01")
    assert ["pactl", "set-default-sink", "bluez_output.AA_BB_CC_DD_EE_01.1"] in pactl["calls"]


def test_routing_leaves_the_default_alone_when_the_sink_never_appears(pactl, monkeypatch):
    pactl["state"]["sinks"] = SINKS
    monkeypatch.setattr(bt, "_SINK_WAIT_SECS", 0.0)
    bt._route_audio("AA:BB:CC:DD:EE:09")
    assert not any(c[:2] == ["pactl", "set-default-sink"] for c in pactl["calls"])
    # The voice is still pinned: that must not depend on the speaker being found.
    assert ["pinned"] in pactl["calls"]


def test_routing_waits_for_a_sink_that_registers_late(pactl):
    pactl["state"]["sinks"] = ""      # not there on the first poll

    seen = {"n": 0}
    real = bt._bt_sink_for

    def late(mac, out):
        seen["n"] += 1
        if seen["n"] >= 3:
            return real(mac, SINKS)
        return real(mac, out)

    bt._bt_sink_for = late
    try:
        bt._route_audio("AA:BB:CC:DD:EE:01")
    finally:
        bt._bt_sink_for = real
    assert ["pactl", "set-default-sink", "bluez_output.AA_BB_CC_DD_EE_01.1"] in pactl["calls"]


# ── the voice pin is the same on the way back ─────────────────────────────────

def test_the_voice_is_pinned_to_the_internal_sink_after_a_disconnect(monkeypatch):
    audio = pytest.importorskip("core.audio")  # needs sounddevice (run on the Pi)
    from core import config
    monkeypatch.setattr(audio, "get_pulseaudio_sinks", lambda: {"internal": "echo_cancel.sink"})
    monkeypatch.setattr(audio, "get_internal_speaker_sink", lambda: "echo_cancel.sink")
    monkeypatch.setattr(bt.subprocess, "run", lambda cmd, **kw: None)
    monkeypatch.setattr(config, "VOICE_OUTPUT_DEVICE", "bluez_output.AA_BB_CC_DD_EE_01.1")
    bt._restore_local_audio()
    # Previously this was set to None and leaned on the default sink having been
    # restored, which is only true while that restore succeeds.
    assert config.VOICE_OUTPUT_DEVICE == "echo_cancel.sink"


# ── the scan always stops ─────────────────────────────────────────────────────

def test_the_scan_is_turned_off_when_the_scan_completes(fake_bt):
    child = fake_bt["make"]({})
    bt.scan(timeout=0)
    assert "scan off" in child.sent
    assert child.sent.index("scan on") < child.sent.index("scan off")
    assert child.closed is True


def test_a_failed_scan_off_does_not_skip_the_quit(fake_bt):
    child = fake_bt["make"]({})
    child.raise_on = "scan off"
    bt.scan(timeout=0)
    assert "scan off" in child.sent and "quit" in child.sent
    assert child.closed is True


def test_nothing_is_turned_off_if_the_scan_never_started(fake_bt):
    child = fake_bt["make"]({})
    child.raise_on = "devices"      # fails before `scan on` is ever sent
    bt.scan(timeout=0)
    assert "scan on" not in child.sent
    assert "scan off" not in child.sent
    assert child.closed is True
