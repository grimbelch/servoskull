"""Given what is true and what we want, the steps that close the gap.

Pure: no D-Bus, no subprocesses, no clock beyond what is passed in. Every decision
about Bluetooth lives here and is therefore testable without a speaker in the room,
which is the point — the faults in the old implementation were all decisions
(the wrong speaker, success never checked, a parameter that was never read), not
transport problems.
"""

from __future__ import annotations

from core.bt.model import Action, Desired, Snapshot


def plan(actual: Snapshot, desired: Desired, now: float = 0.0) -> list[Action]:
    """The actions that would move `actual` towards `desired`, in order.

    An empty list means there is nothing to do, which is the steady state and by
    far the most common answer. Each call returns at most one connect or one
    disconnect: the caller applies, takes a fresh snapshot and asks again, so a
    half-applied plan is never acted on as though it were complete.
    """
    steps: list[Action] = []

    # Nothing can be done with the radio off, and this is also the recovery path
    # after someone runs `bluetoothctl power off` or the adapter resets.
    if not actual.powered:
        steps.append(Action("power_on"))
        return steps

    steps += _discovery_steps(actual, desired, now)

    wanted = desired.speaker
    if wanted is None:
        # No speaker wanted: drop anything still connected and bring audio home.
        for dev in actual.connected():
            return steps + [Action("disconnect", dev.mac, dev.name)]
        if actual.default_sink and actual.default_sink.startswith("bluez"):
            steps.append(Action("unroute", detail=actual.default_sink))
        return steps

    target = actual.device(wanted)
    if target is None:
        # Known to nobody: discovery has to find it before anything else can happen,
        # and saying so beats silently doing nothing.
        return steps + [Action("start_discovery", wanted, "target unknown")]

    # Anything else connected is competing for the same system audio.
    for dev in actual.connected():
        if dev.mac != target.mac:
            return steps + [Action("disconnect", dev.mac, dev.name)]

    if not target.trusted:
        # Trust first: an untrusted device needs the agent for every reconnect, and
        # the reconnect happens when nobody is listening.
        steps.append(Action("trust", target.mac, target.name))

    if not target.connected:
        return steps + [Action("connect", target.mac, target.name)]

    # Connected. Now the audio has to actually go there.
    if actual.sink is None:
        # The sink appears a moment after the link does; waiting is not an action.
        return steps
    if actual.default_sink != actual.sink:
        steps.append(Action("route", target.mac, actual.sink))

    return steps


def _discovery_steps(actual: Snapshot, desired: Desired, now: float) -> list[Action]:
    """Discovery runs while it is wanted and stops when it is not.

    Left running it costs power and air time, which is what the old implementation
    risked whenever its `scan off` was skipped.
    """
    wants = desired.discovering_until > now
    if wants and not actual.discovering:
        return [Action("start_discovery")]
    if not wants and actual.discovering:
        return [Action("stop_discovery")]
    return []


def settled(actual: Snapshot, desired: Desired, now: float = 0.0) -> bool:
    """True when there is nothing left to do."""
    return not plan(actual, desired, now)
