"""Bluetooth as a desired state the unit converges on, rather than a script it runs.

The old implementation drove `bluetoothctl` through pexpect and ran once: pair,
connect, check, find the sink, set it, pin the voice. Nothing watched afterwards,
so a speaker that dropped at three in the morning left the skull quietly playing
to nothing until somebody noticed.

This package is four pieces:

- `model`   — what a device is and what we want to be true. Pure data.
- `plan`    — given what is true and what we want, the actions that close the gap.
              Pure, no I/O, and where every decision lives.
- `bluez`   — BlueZ over D-Bus (dbus-fast), the only part that touches the system.
- `manager` — one owner: an asyncio loop on its own thread that applies the plan,
              on every BlueZ signal and on a periodic tick. Being the only writer
              is what makes concurrent commands safe without locks.

`core.bluetooth_ctrl` stays the public face for callers and tool handlers.
"""
