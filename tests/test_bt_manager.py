"""The Bluetooth manager, driven against a fake BlueZ.

A hand-written fake rather than a mocked D-Bus daemon: the surface the manager
depends on is seven methods, and python-dbusmock's bluez5 template implements
Pair() without agents and always succeeding, so it would not be faithful where it
matters most. This fake can fail, refuse and change under us (run: python -m pytest tests).
"""
import threading
import time

import pytest

from core.bt.manager import BluetoothManager
from core.bt.model import Device, Snapshot

JBL = "AA:BB:CC:DD:EE:01"
NEST = "AA:BB:CC:DD:EE:02"


class FakeBus:
    """Enough of BlueZ to converge against, and to misbehave on purpose."""

    def __init__(self, devices=(), powered=True):
        self.devices = {d.mac: d for d in devices}
        self.powered = powered
        self.discovering = False
        self.calls: list[str] = []
        self.fail_on: set[str] = set()
        self._on_change = None

    # the surface the manager uses
    async def connect_bus(self):
        self.calls.append("connect_bus")

    async def close(self):
        pass

    def on_change(self, cb):
        self._on_change = cb

    def notify(self):
        if self._on_change:
            self._on_change()

    async def snapshot(self):
        return Snapshot(powered=self.powered, discovering=self.discovering,
                        devices=tuple(self.devices.values()), adapter_path="/org/bluez/hci0")

    async def power_on(self):
        self._record("power_on")
        self.powered = True

    async def set_trusted(self, mac, trusted=True):
        self._record(f"trust:{mac}")
        self.devices[mac] = Device(**{**self.devices[mac].__dict__, "trusted": trusted})

    async def connect(self, mac):
        self._record(f"connect:{mac}")
        self.devices[mac] = Device(**{**self.devices[mac].__dict__, "connected": True})

    async def disconnect(self, mac):
        self._record(f"disconnect:{mac}")
        self.devices[mac] = Device(**{**self.devices[mac].__dict__, "connected": False})

    async def start_discovery(self):
        self._record("start_discovery")
        self.discovering = True

    async def stop_discovery(self):
        self._record("stop_discovery")
        self.discovering = False

    def _record(self, what):
        self.calls.append(what)
        key = what.split(":")[0]
        if key in self.fail_on or what in self.fail_on:
            raise RuntimeError(f"org.bluez.Error.Failed: {what} refused")


def dev(mac, **kw):
    kw.setdefault("name", mac[-5:])
    return Device(address=mac, **kw)


@pytest.fixture
def routing(monkeypatch):
    """Audio routing as in-memory state rather than pactl calls."""
    from core.bt import audio_route
    state = {"default": "alsa_output.card", "sinks": {}, "pinned": 0}
    monkeypatch.setattr(audio_route, "current_sink_for",
                        lambda mac: state["sinks"].get((mac or "").upper()))
    monkeypatch.setattr(audio_route, "default_sink", lambda: state["default"])
    monkeypatch.setattr(audio_route, "internal_sink", lambda: "echo_cancel.sink")
    monkeypatch.setattr(audio_route, "pin_voice_to_internal",
                        lambda: state.__setitem__("pinned", state["pinned"] + 1))

    def set_default(name):
        if state.get("refuse"):
            return False
        state["default"] = name
        return True
    monkeypatch.setattr(audio_route, "set_default_sink", set_default)
    return state


@pytest.fixture
def mgr(routing):
    made = {}

    def build(bus, tick=3600.0):
        # No settle delay: the fake applies its changes synchronously.
        m = BluetoothManager(bus=bus, tick_secs=tick, settle_secs=0.0)
        assert m.start(timeout=5) is True
        made["m"] = m
        return m
    yield build
    if "m" in made:
        made["m"].stop()


# ── converging ────────────────────────────────────────────────────────────────

def test_it_connects_trusts_and_routes_in_one_reconcile(mgr, routing):
    bus = FakeBus([dev(JBL, paired=True)])
    routing["sinks"][JBL] = "bluez_output.AA_BB_CC_DD_EE_01.1"
    m = mgr(bus)
    out = m.set_speaker(JBL)
    assert out.ok, out.failures
    assert bus.devices[JBL].connected is True
    assert bus.devices[JBL].trusted is True
    assert routing["default"] == "bluez_output.AA_BB_CC_DD_EE_01.1"
    assert routing["pinned"] >= 1          # voice stays on the internal speaker


def test_a_second_reconcile_does_nothing(mgr, routing):
    bus = FakeBus([dev(JBL, paired=True)])
    routing["sinks"][JBL] = "bluez_output.x"
    m = mgr(bus)
    m.set_speaker(JBL)
    before = list(bus.calls)
    out = m.reconcile()
    assert out.actions == []               # settled
    assert bus.calls == before


def test_the_other_speaker_is_dropped_not_the_wanted_one(mgr, routing):
    bus = FakeBus([dev(NEST, paired=True, trusted=True, connected=True),
                   dev(JBL, paired=True, trusted=True)])
    routing["sinks"][JBL] = "bluez_output.jbl"
    m = mgr(bus)
    m.set_speaker(JBL)
    assert bus.devices[NEST].connected is False
    assert bus.devices[JBL].connected is True
    assert routing["default"] == "bluez_output.jbl"


def test_wanting_none_disconnects_and_brings_audio_home(mgr, routing):
    bus = FakeBus([dev(JBL, paired=True, trusted=True, connected=True)])
    routing["default"] = "bluez_output.jbl"
    m = mgr(bus)
    out = m.set_speaker(None)
    assert out.ok, out.failures
    assert bus.devices[JBL].connected is False
    assert routing["default"] == "echo_cancel.sink"


def test_a_powered_down_adapter_is_powered_up_first(mgr, routing):
    bus = FakeBus([dev(JBL, paired=True, trusted=True)], powered=False)
    routing["sinks"][JBL] = "bluez_output.jbl"
    m = mgr(bus)
    m.set_speaker(JBL)
    assert bus.calls[1] == "power_on"      # after connect_bus
    assert bus.devices[JBL].connected is True


# ── failing honestly ──────────────────────────────────────────────────────────

def test_a_refused_connect_is_reported_not_swallowed(mgr, routing):
    bus = FakeBus([dev(JBL, paired=True, trusted=True)])
    bus.fail_on.add("connect")
    m = mgr(bus)
    out = m.set_speaker(JBL)
    assert out.ok is False
    assert any("connect" in f and "refused" in f for f in out.failures)


def test_a_refused_route_is_reported(mgr, routing):
    bus = FakeBus([dev(JBL, paired=True, trusted=True, connected=True)])
    routing["sinks"][JBL] = "bluez_output.jbl"
    routing["refuse"] = True
    m = mgr(bus)
    out = m.set_speaker(JBL)
    assert out.ok is False and "pactl refused" in out.failures[0]


def test_an_unknown_device_asks_for_discovery_rather_than_failing(mgr, routing):
    bus = FakeBus([])
    m = mgr(bus)
    out = m.set_speaker(JBL)
    assert "start_discovery" in bus.calls
    assert out.ok


# ── self-healing, which is the whole point ────────────────────────────────────

def test_a_speaker_that_drops_is_reconnected_on_the_next_reconcile(mgr, routing):
    bus = FakeBus([dev(JBL, paired=True)])
    routing["sinks"][JBL] = "bluez_output.jbl"
    m = mgr(bus)
    m.set_speaker(JBL)
    # Three in the morning: the link goes and nobody asked for anything.
    bus.devices[JBL] = dev(JBL, paired=True, trusted=True, connected=False)
    m.reconcile()
    assert bus.devices[JBL].connected is True


def test_audio_routed_away_behind_our_back_is_routed_again(mgr, routing):
    bus = FakeBus([dev(JBL, paired=True)])
    routing["sinks"][JBL] = "bluez_output.jbl"
    m = mgr(bus)
    m.set_speaker(JBL)
    routing["default"] = "alsa_output.card"      # PipeWire restarted
    m.reconcile()
    assert routing["default"] == "bluez_output.jbl"


def test_a_bluez_signal_triggers_a_reconcile_without_being_asked(mgr, routing):
    bus = FakeBus([dev(JBL, paired=True)])
    routing["sinks"][JBL] = "bluez_output.jbl"
    m = mgr(bus)
    m.set_speaker(JBL)
    bus.devices[JBL] = dev(JBL, paired=True, trusted=True, connected=False)
    bus.notify()                                  # what InterfacesAdded would do
    deadline = time.time() + 5
    while time.time() < deadline and not bus.devices[JBL].connected:
        time.sleep(0.05)
    assert bus.devices[JBL].connected is True


def test_the_tick_reconciles_with_nobody_asking(routing):
    bus = FakeBus([dev(JBL, paired=True)])
    routing["sinks"][JBL] = "bluez_output.jbl"
    m = BluetoothManager(bus=bus, tick_secs=0.2, settle_secs=0.0)
    assert m.start(timeout=5)
    try:
        m.set_speaker(JBL)
        bus.devices[JBL] = dev(JBL, paired=True, trusted=True, connected=False)
        deadline = time.time() + 5
        while time.time() < deadline and not bus.devices[JBL].connected:
            time.sleep(0.05)
        assert bus.devices[JBL].connected is True
    finally:
        m.stop()


# ── one owner ─────────────────────────────────────────────────────────────────

def test_two_commands_at_once_do_not_interleave(mgr, routing):
    bus = FakeBus([dev(JBL, paired=True), dev(NEST, paired=True)])
    routing["sinks"][JBL] = "bluez_output.jbl"
    m = mgr(bus)
    errors = []

    def ask(mac):
        try:
            m.set_speaker(mac)
        except Exception as e:      # pragma: no cover
            errors.append(e)
    threads = [threading.Thread(target=ask, args=(JBL,)),
               threading.Thread(target=ask, args=(None,))]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=30)
    assert errors == []
    # Whichever won, the end state is coherent: it is not both connected and not.
    m.reconcile()
    connected = [d.mac for d in bus.devices.values() if d.connected]
    assert connected == ([JBL] if m.desired.speaker == JBL else [])


# ── not hammering a speaker that is switched off ──────────────────────────────

def test_a_failing_connect_is_not_retried_immediately(mgr, routing):
    # The real speaker was off; the reconciler called connect three times in one
    # pass and blew its own deadline.
    bus = FakeBus([dev(JBL, paired=True, trusted=True)])
    bus.fail_on.add("connect")
    m = mgr(bus)
    m.set_speaker(JBL)
    first = bus.calls.count(f"connect:{JBL}")
    assert first == 1
    out = m.reconcile()
    assert bus.calls.count(f"connect:{JBL}") == 1          # still one
    assert "next attempt in" in out.failures[0]


def test_the_wait_grows_while_it_keeps_failing():
    # Pure arithmetic, so test it as such: a speaker off for the afternoon should
    # be tried every couple of minutes, not every twenty seconds.
    from core.bt.manager import BACKOFF_SECS, BluetoothManager
    m = BluetoothManager(bus=FakeBus())
    key = ("connect", JBL)
    waits = []
    for _ in range(len(BACKOFF_SECS) + 2):
        m._note_failure(key, 1000.0)
        waits.append(m._backoff_remaining(key, 1000.0))
    assert waits == sorted(waits)                  # never gets shorter
    assert waits[0] == BACKOFF_SECS[0]
    assert waits[-1] == BACKOFF_SECS[-1]           # and is capped


def test_the_backoff_only_applies_to_the_slow_actions():
    from core.bt.manager import BluetoothManager
    m = BluetoothManager(bus=FakeBus())
    m._note_failure(("disconnect", JBL), 1000.0)
    assert m._backoff_remaining(("disconnect", JBL), 1000.0) == 0.0


def test_the_wait_runs_down_with_the_clock():
    from core.bt.manager import BACKOFF_SECS, BluetoothManager
    m = BluetoothManager(bus=FakeBus())
    key = ("connect", JBL)
    m._note_failure(key, 1000.0)
    assert m._backoff_remaining(key, 1000.0 + BACKOFF_SECS[0] / 2) == pytest.approx(
        BACKOFF_SECS[0] / 2)
    assert m._backoff_remaining(key, 1000.0 + BACKOFF_SECS[0] + 1) == 0.0


def test_a_successful_connect_clears_the_backoff(mgr, routing):
    bus = FakeBus([dev(JBL, paired=True, trusted=True)])
    bus.fail_on.add("connect")
    m = mgr(bus)
    m.set_speaker(JBL)
    assert ("connect", JBL) in m._failures
    bus.fail_on.clear()
    m._failures.clear()                                     # as the backoff expiring
    m.reconcile()
    assert ("connect", JBL) not in m._failures
    assert bus.devices[JBL].connected is True


def test_a_drop_after_a_success_is_reconnected_at_once(mgr, routing):
    # Failures back off; a link that worked and then dropped must not.
    bus = FakeBus([dev(JBL, paired=True)])
    routing["sinks"][JBL] = "bluez_output.jbl"
    m = mgr(bus)
    m.set_speaker(JBL)
    assert m._failures == {}
    bus.devices[JBL] = dev(JBL, paired=True, trusted=True, connected=False)
    m.reconcile()
    assert bus.devices[JBL].connected is True


def test_a_failure_is_stamped_when_it_happens_not_when_the_pass_began(mgr, routing):
    """A connect that blocks for 25s and then fails was recorded as having failed
    25s ago, so the backoff had already expired and the next pass went at it again.
    Driving the real speaker is what showed it."""
    import time as _t
    bus = FakeBus([dev(JBL, paired=True, trusted=True)])

    slow = {"n": 0}
    real_connect = bus.connect

    async def slow_connect(mac):
        slow["n"] += 1
        await __import__("asyncio").sleep(0.4)      # stands in for 25 real seconds
        raise RuntimeError("org.bluez.Error.Failed: connect refused")
    bus.connect = slow_connect
    m = mgr(bus)
    m.set_speaker(JBL)
    assert slow["n"] == 1
    # The backoff must still have time left on it the instant the failure returns.
    assert m._backoff_remaining(("connect", JBL), _t.monotonic()) > 0
    out = m.reconcile()
    assert slow["n"] == 1                            # not retried
    assert "next attempt in" in out.failures[0]
    bus.connect = real_connect
