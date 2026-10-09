"""The Bluetooth planner: what it decides, with no hardware anywhere near it.

Every Bluetooth fault found in review was a decision, not a transport problem --
the wrong speaker routed, success reported without checking, a parameter computed
and never read, `scan off` skippable. All of those are decisions this module makes
and these tests can hold it to (run: python -m pytest tests).
"""
from core.bt.model import Desired, Device, Snapshot
from core.bt.plan import plan, settled

JBL = "AA:BB:CC:DD:EE:01"
NEST = "AA:BB:CC:DD:EE:02"


def snap(**kw):
    kw.setdefault("powered", True)
    return Snapshot(**kw)


def dev(mac, **kw):
    kw.setdefault("name", mac[-5:])
    return Device(address=mac, **kw)


def kinds(actions):
    return [a.kind for a in actions]


# ── the radio ─────────────────────────────────────────────────────────────────

def test_a_powered_down_adapter_is_powered_up_first():
    actions = plan(Snapshot(powered=False), Desired(speaker=JBL))
    assert kinds(actions) == ["power_on"]


def test_nothing_else_is_attempted_while_it_is_off():
    # Also the recovery path after `bluetoothctl power off` or an adapter reset.
    actions = plan(Snapshot(powered=False, devices=(dev(JBL, paired=True),)),
                   Desired(speaker=JBL))
    assert kinds(actions) == ["power_on"]


# ── converging on a speaker ───────────────────────────────────────────────────

def test_a_known_untrusted_device_is_trusted_then_connected():
    actions = plan(snap(devices=(dev(JBL, paired=True),)), Desired(speaker=JBL))
    assert kinds(actions) == ["trust", "connect"]


def test_an_already_trusted_device_is_just_connected():
    actions = plan(snap(devices=(dev(JBL, paired=True, trusted=True),)),
                   Desired(speaker=JBL))
    assert kinds(actions) == ["connect"]


def test_a_device_nobody_knows_starts_discovery_rather_than_nothing():
    actions = plan(snap(devices=()), Desired(speaker=JBL))
    assert kinds(actions) == ["start_discovery"]
    assert actions[0].mac == JBL


def test_a_connected_speaker_with_a_sink_gets_the_audio():
    actions = plan(snap(devices=(dev(JBL, paired=True, trusted=True, connected=True),),
                        sink="bluez_output.AA_BB_CC_DD_EE_01.1", default_sink="alsa_output.card"),
                   Desired(speaker=JBL))
    assert kinds(actions) == ["route"]
    assert actions[0].detail == "bluez_output.AA_BB_CC_DD_EE_01.1"


def test_waiting_for_the_sink_is_not_an_action():
    # It appears a moment after the link; the old code slept one second and hoped.
    actions = plan(snap(devices=(dev(JBL, paired=True, trusted=True, connected=True),),
                        sink=None, default_sink="alsa_output.card"),
                   Desired(speaker=JBL))
    assert actions == []


def test_once_connected_and_routed_there_is_nothing_to_do():
    s = snap(devices=(dev(JBL, paired=True, trusted=True, connected=True),),
             sink="bluez_output.x", default_sink="bluez_output.x")
    assert plan(s, Desired(speaker=JBL)) == []
    assert settled(s, Desired(speaker=JBL)) is True


# ── the wrong speaker ─────────────────────────────────────────────────────────

def test_another_connected_speaker_is_dropped_first():
    # This is the fault that routed audio to whichever device pactl listed first.
    actions = plan(snap(devices=(dev(NEST, paired=True, trusted=True, connected=True),
                                 dev(JBL, paired=True, trusted=True))),
                   Desired(speaker=JBL))
    assert kinds(actions) == ["disconnect"]
    assert actions[0].mac == NEST


def test_it_does_not_disconnect_the_speaker_it_is_converging_on():
    actions = plan(snap(devices=(dev(JBL, paired=True, trusted=True, connected=True),),
                        sink="bluez_output.x", default_sink="bluez_output.x"),
                   Desired(speaker=JBL))
    assert "disconnect" not in kinds(actions)


# ── wanting no speaker at all ─────────────────────────────────────────────────

def test_wanting_none_disconnects_what_is_connected():
    actions = plan(snap(devices=(dev(JBL, connected=True, paired=True),)), Desired(speaker=None))
    assert kinds(actions) == ["disconnect"]
    assert actions[0].mac == JBL


def test_wanting_none_brings_the_audio_home():
    actions = plan(snap(devices=(), default_sink="bluez_output.stale"), Desired(speaker=None))
    assert kinds(actions) == ["unroute"]


def test_wanting_none_with_nothing_connected_is_settled():
    assert plan(snap(devices=(), default_sink="alsa_output.card"), Desired(speaker=None)) == []


def test_disconnecting_several_takes_them_one_at_a_time():
    # One connect or disconnect per plan: the caller re-snapshots between, so a
    # half-applied plan is never treated as finished.
    s = snap(devices=(dev(JBL, connected=True), dev(NEST, connected=True)))
    actions = plan(s, Desired(speaker=None))
    assert kinds(actions) == ["disconnect"]


# ── discovery ─────────────────────────────────────────────────────────────────

def test_discovery_starts_when_wanted_and_stops_when_not():
    want = Desired(speaker=None, discovering_until=100.0)
    assert kinds(plan(snap(discovering=False), want, now=50.0)) == ["start_discovery"]
    assert plan(snap(discovering=True), want, now=50.0) == []


def test_discovery_is_stopped_once_its_time_is_up():
    # Left running it costs power and air time; the old `scan off` was skippable.
    done = Desired(speaker=None, discovering_until=100.0)
    assert kinds(plan(snap(discovering=True), done, now=101.0)) == ["stop_discovery"]


def test_discovery_being_on_does_not_stop_the_speaker_converging():
    actions = plan(snap(discovering=True, devices=(dev(JBL, paired=True, trusted=True),)),
                   Desired(speaker=JBL, discovering_until=100.0), now=50.0)
    assert kinds(actions) == ["connect"]


# ── self-healing, which the old implementation could not do at all ────────────

def test_a_speaker_that_drops_is_reconnected():
    # Three in the morning: the link goes, nothing else changes, and the next
    # reconcile notices.
    s = snap(devices=(dev(JBL, paired=True, trusted=True, connected=False),),
             default_sink="alsa_output.card")
    assert kinds(plan(s, Desired(speaker=JBL))) == ["connect"]


def test_audio_routed_away_behind_our_back_is_routed_again():
    # PipeWire restarts, or something else sets the default sink.
    s = snap(devices=(dev(JBL, paired=True, trusted=True, connected=True),),
             sink="bluez_output.x", default_sink="alsa_output.card")
    assert kinds(plan(s, Desired(speaker=JBL))) == ["route"]


def test_trust_lost_is_restored():
    s = snap(devices=(dev(JBL, paired=True, trusted=False, connected=True),),
             sink="bluez_output.x", default_sink="bluez_output.x")
    assert kinds(plan(s, Desired(speaker=JBL))) == ["trust"]
