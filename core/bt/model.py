"""What a Bluetooth device is, and what we want to be true about it."""

from __future__ import annotations

from dataclasses import dataclass, field, replace


@dataclass(frozen=True)
class Device:
    """One device as BlueZ currently describes it."""
    address: str
    name: str = ""
    paired: bool = False
    trusted: bool = False
    connected: bool = False
    path: str = ""          # its D-Bus object path

    @property
    def mac(self) -> str:
        """The address in the upper-case form the rest of the code passes around."""
        return self.address.upper()


@dataclass(frozen=True)
class Snapshot:
    """Everything known about the adapter and its devices at one instant."""
    powered: bool = False
    discovering: bool = False
    devices: tuple[Device, ...] = ()
    adapter_path: str = ""
    # The sink the speaker's audio would play through, when one exists yet.
    sink: str | None = None
    default_sink: str | None = None

    def device(self, mac: str) -> Device | None:
        mac = (mac or "").upper()
        return next((d for d in self.devices if d.mac == mac), None)

    def connected(self) -> tuple[Device, ...]:
        return tuple(d for d in self.devices if d.connected)


@dataclass(frozen=True)
class Desired:
    """What the unit is trying to be true. The whole point of the package.

    `speaker` is the one device that should be connected and carrying system audio.
    None means no Bluetooth speaker is wanted, which is also a state to converge on:
    anything still connected gets dropped and audio comes home.
    """
    speaker: str | None = None
    # Set while the user is choosing a device, so discovery runs and then stops.
    discovering_until: float = 0.0

    def with_speaker(self, mac: str | None) -> "Desired":
        return replace(self, speaker=(mac or "").upper() or None)


@dataclass(frozen=True)
class Action:
    """One step towards the desired state. Named, so a plan can be asserted on."""
    kind: str               # power_on | trust | connect | disconnect | route | unroute
                            # | start_discovery | stop_discovery
    mac: str = ""
    detail: str = ""

    def __str__(self) -> str:
        bits = [self.kind]
        if self.mac:
            bits.append(self.mac)
        if self.detail:
            bits.append(f"({self.detail})")
        return " ".join(bits)


@dataclass
class Outcome:
    """What came of applying a plan, for the caller and the log."""
    ok: bool = True
    actions: list[str] = field(default_factory=list)
    failures: list[str] = field(default_factory=list)

    def note(self, action: Action) -> None:
        self.actions.append(str(action))

    def fail(self, action: Action, why: str) -> None:
        self.ok = False
        self.failures.append(f"{action}: {why}")
