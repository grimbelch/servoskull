"""BlueZ over D-Bus, through dbus-fast.

The only module here that touches the system, and deliberately thin: it reads
properties and calls methods, and every decision about what to call lives in
`plan`. That split is what lets the decisions be tested without a speaker.

Why D-Bus rather than driving bluetoothctl: this is the API bluetoothctl is itself
a client of. Properties come back typed instead of grepped out of prose, failures
arrive as org.bluez.Error.* rather than a prompt that never came, and -- the part
polling cannot do at all -- InterfacesAdded and PropertiesChanged say the moment
something changes, which is what lets a dropped speaker be noticed at once.
"""

from __future__ import annotations

from core.bt.model import Device, Snapshot

BLUEZ = "org.bluez"
ADAPTER_IFACE = "org.bluez.Adapter1"
DEVICE_IFACE = "org.bluez.Device1"
OBJECT_MANAGER = "org.freedesktop.DBus.ObjectManager"
PROPERTIES = "org.freedesktop.DBus.Properties"


class BluezUnavailable(RuntimeError):
    """BlueZ is not reachable on the system bus."""


class BluezBus:
    """A narrow view of BlueZ: enough for the planner's actions and no more."""

    def __init__(self) -> None:
        self._bus = None
        self._manager = None
        self._adapter_path = ""
        self._on_change = None

    # ── connecting ────────────────────────────────────────────────────────────

    async def connect_bus(self) -> None:
        from dbus_fast.aio import MessageBus
        from dbus_fast.constants import BusType
        try:
            self._bus = await MessageBus(bus_type=BusType.SYSTEM).connect()
            intro = await self._bus.introspect(BLUEZ, "/")
            root = self._bus.get_proxy_object(BLUEZ, "/", intro)
            self._manager = root.get_interface(OBJECT_MANAGER)
        except Exception as e:
            raise BluezUnavailable(str(e)) from e
        self._manager.on_interfaces_added(self._changed_2)
        self._manager.on_interfaces_removed(self._changed_2)

    async def close(self) -> None:
        if self._bus is not None:
            try:
                self._bus.disconnect()
            except Exception:
                pass
            self._bus = None

    def on_change(self, callback) -> None:
        """Called with no arguments whenever BlueZ reports anything changing."""
        self._on_change = callback

    def _changed_2(self, *_args) -> None:
        if self._on_change:
            self._on_change()

    # ── reading ───────────────────────────────────────────────────────────────

    async def snapshot(self) -> Snapshot:
        """Adapter and devices as BlueZ has them this instant."""
        objects = await self._manager.call_get_managed_objects()
        powered = discovering = False
        adapter_path = ""
        devices: list[Device] = []
        for path, ifaces in objects.items():
            if ADAPTER_IFACE in ifaces and not adapter_path:
                a = ifaces[ADAPTER_IFACE]
                adapter_path = path
                powered = bool(_val(a, "Powered", False))
                discovering = bool(_val(a, "Discovering", False))
            if DEVICE_IFACE in ifaces:
                d = ifaces[DEVICE_IFACE]
                addr = _val(d, "Address", "")
                if not addr:
                    continue
                devices.append(Device(
                    address=str(addr).upper(),
                    name=str(_val(d, "Alias", "") or _val(d, "Name", "") or ""),
                    paired=bool(_val(d, "Paired", False)),
                    trusted=bool(_val(d, "Trusted", False)),
                    connected=bool(_val(d, "Connected", False)),
                    path=path,
                ))
        self._adapter_path = adapter_path
        return Snapshot(powered=powered, discovering=discovering,
                        devices=tuple(devices), adapter_path=adapter_path)

    # ── acting ────────────────────────────────────────────────────────────────

    async def power_on(self) -> None:
        props = await self._props(self._adapter_path)
        from dbus_fast import Variant
        await props.call_set(ADAPTER_IFACE, "Powered", Variant("b", True))

    async def set_trusted(self, mac: str, trusted: bool = True) -> None:
        path = await self._device_path(mac)
        props = await self._props(path)
        from dbus_fast import Variant
        await props.call_set(DEVICE_IFACE, "Trusted", Variant("b", trusted))

    async def connect(self, mac: str) -> None:
        iface = await self._device(mac)
        await iface.call_connect()

    async def disconnect(self, mac: str) -> None:
        iface = await self._device(mac)
        await iface.call_disconnect()

    async def pair(self, mac: str) -> None:
        iface = await self._device(mac)
        await iface.call_pair()

    async def start_discovery(self) -> None:
        iface = await self._adapter()
        await iface.call_start_discovery()

    async def stop_discovery(self) -> None:
        iface = await self._adapter()
        await iface.call_stop_discovery()

    # ── plumbing ──────────────────────────────────────────────────────────────

    async def _iface(self, path: str, name: str):
        intro = await self._bus.introspect(BLUEZ, path)
        return self._bus.get_proxy_object(BLUEZ, path, intro).get_interface(name)

    async def _props(self, path: str):
        return await self._iface(path, PROPERTIES)

    async def _adapter(self):
        if not self._adapter_path:
            await self.snapshot()
        if not self._adapter_path:
            raise BluezUnavailable("no Bluetooth adapter")
        return await self._iface(self._adapter_path, ADAPTER_IFACE)

    async def _device_path(self, mac: str) -> str:
        snap = await self.snapshot()
        dev = snap.device(mac)
        if dev is None or not dev.path:
            raise BluezUnavailable(f"BlueZ does not know {mac}")
        return dev.path

    async def _device(self, mac: str):
        return await self._iface(await self._device_path(mac), DEVICE_IFACE)


def _val(props: dict, key: str, default):
    """A property's value, whether dbus-fast handed us a Variant or a plain value."""
    item = props.get(key)
    if item is None:
        return default
    return getattr(item, "value", item)
