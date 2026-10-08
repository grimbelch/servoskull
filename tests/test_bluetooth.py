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
