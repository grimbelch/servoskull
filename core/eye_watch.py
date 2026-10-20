"""
Turns the state of the world into the eye LEDs' status layers.

One background thread gathers facts about the speaker, casting, the network, the
printer, held notices, reminders, temperature, power, quiet hours and presence
(gather()), turns them into lights (compose(), pure and unit-tested in
tests/test_eye_watch.py), and hands them to core/eyes.py. It also notices the
moments: a speaker connecting or dropping, an under-voltage event, someone
walking in while a held notice waits to be told.

    left eye (links)    offline        amber flicker
                        reconnecting   blue, blinking slowly
                        BT speaker     dim steady blue
                        casting        dim steady violet
    right eye (tasks)   print failed   amber double-blink        (held notice)
                        print done     green pulse               (held notice)
                        reminder due   white blink               (until acknowledged)
                        missed         slow white pulse          (silent mode dropped one)
                        printing       cyan breathing; steady when paused
    both                overheating    orange pulse
    brightness          sleep hours 25% and nothing blinks; silent 50%;
                        empty room 50%
"""

from __future__ import annotations

import socket
import subprocess
import threading
import time
from dataclasses import dataclass, field

from core import config, eyes, notices
from core import eye_states as es

TICK_SECS = 1.0
_NET_PROBE = ("api.anthropic.com", 443)
_NET_EVERY_SECS = 30.0
_NET_FAILS_OFFLINE = 2


@dataclass
class Facts:
    bt_connected: bool = False
    bt_reconnecting: bool = False
    casting: bool = False
    offline: bool = False
    printer_state: str = ""          # Bambu gcode_state, upper case
    notices: list[str] = field(default_factory=list)   # held kinds, oldest first
    reminder_due: bool = False
    hot: bool = False
    sleep: bool = False
    silent: bool = False
    room_empty: bool = False


def compose(f: Facts) -> tuple[list[es.Light], list[es.Light], es.Light | None, float, bool]:
    """(links, tasks, health, scale, calm) for eyes.set_status()."""
    links: list[es.Light] = []
    if f.offline:
        links.append(es.Light(es.AMBER, "flicker", 0.6, name="offline"))
    if f.bt_reconnecting and not f.bt_connected:
        links.append(es.Light(es.BT_BLUE, "blink", 0.6, period=2.0, name="bt reconnecting"))
    if f.bt_connected:
        links.append(es.Light(es.BT_BLUE, "steady", 0.3, name="bt speaker"))
    if f.casting:
        links.append(es.Light(es.CAST_VIOLET, "steady", 0.3, name="casting"))

    tasks: list[es.Light] = []
    for kind in f.notices:
        if kind == notices.PRINT_ERROR:
            tasks.append(es.Light(es.AMBER, "double", 1.0, name="print error"))
        elif kind == notices.PRINT_DONE:
            tasks.append(es.Light(es.GREEN, "pulse", 0.9, name="print done"))
        elif kind == notices.MISSED:
            tasks.append(es.Light(es.WHITE, "pulse", 0.5, white=True, period=4.0, name="missed"))
    if f.reminder_due:
        tasks.insert(0, es.Light(es.WHITE, "blink", 0.8, white=True, period=1.0, name="reminder"))
    if f.printer_state in ("RUNNING", "PREPARE"):
        tasks.append(es.Light(es.CYAN, "breathe", 0.5, period=5.0, name="printing"))
    elif f.printer_state == "PAUSE":
        tasks.append(es.Light(es.CYAN, "steady", 0.4, name="print paused"))

    health = es.Light(es.ORANGE, "pulse", 1.0, period=3.0, name="overheating") if f.hot else None

    if f.sleep:
        scale, calm = 0.25, True
    elif f.silent or f.room_empty:
        scale, calm = 0.5, False
    else:
        scale, calm = 1.0, False
    return links, tasks, health, scale, calm


# ── Gathering ──────────────────────────────────────────────────────────────────

_offline = False
_net_fails = 0
_hot = False


def _bt_sink_present() -> bool:
    """Whether PipeWire has a Bluetooth output right now."""
    try:
        out = subprocess.run(["pactl", "list", "short", "sinks"], capture_output=True,
                             text=True, timeout=3).stdout
    except Exception:
        return False
    return "bluez_output" in out


def _probe_network() -> None:
    """Can the API's address be reached? Run off the tick: DNS can hang."""
    global _offline, _net_fails
    while True:
        try:
            with socket.create_connection(_NET_PROBE, timeout=4):
                pass
            if _offline:
                print("[eyes] Network back.")
            _net_fails, _offline = 0, False
        except OSError:
            _net_fails += 1
            if _net_fails >= _NET_FAILS_OFFLINE and not _offline:
                _offline = True
                print(f"[eyes] Cannot reach {_NET_PROBE[0]}; showing offline.")
        time.sleep(_NET_EVERY_SECS)


def _is_hot() -> bool:
    global _hot
    from core import temperature
    t = temperature.read_temp_c()
    if t is not None:
        if t >= config.TEMP_WARN_THRESHOLD:
            _hot = True
        elif t <= config.TEMP_CLEAR_THRESHOLD:
            _hot = False
    return _hot


def _printer_state() -> tuple[str, list]:
    from core import bambu_ctrl
    s = bambu_ctrl.get_status_report() or {}
    return str(s.get("gcode_state", "")).upper(), list(s.get("hms") or [])


def _reminder_due() -> bool:
    from core import reminders
    return any(r.get("repeating") for r in reminders.list_all())


def present() -> bool | None:
    """Someone moved within PRESENCE_WINDOW_SECS; None without a rangefinder."""
    from core import proximity
    s = proximity.seconds_since_movement()
    if s is None:
        return None if not proximity.available() else False
    return s < config.PRESENCE_WINDOW_SECS


def gather(bt_connected: bool) -> Facts:
    from core import bluetooth_ctrl, cast_audio, quiet, proximity
    since = proximity.seconds_since_movement()
    return Facts(
        bt_connected=bt_connected,
        bt_reconnecting=bool(bluetooth_ctrl.wanted_speaker()),
        casting=cast_audio.is_configured(),
        offline=_offline,
        printer_state=_printer_state()[0],
        notices=[n.kind for n in notices.pending()],
        reminder_due=_reminder_due(),
        hot=_is_hot(),
        sleep=quiet.is_in_sleep_hours(),
        silent=quiet.is_silent(),
        room_empty=since is not None and since > config.DISPLAY_PRESENCE_TIMEOUT,
    )


# ── Moments ────────────────────────────────────────────────────────────────────

def _settle_printer_notices() -> None:
    """A new print, or the printer clearing its own errors, makes a notice moot."""
    state, hms = _printer_state()
    if state in ("RUNNING", "PREPARE"):
        notices.clear(notices.PRINT_DONE, "a new print started")
        if not hms:
            notices.clear(notices.PRINT_ERROR, "a new print started")
    elif not hms and state not in ("FAILED", "PAUSE") and notices.has(notices.PRINT_ERROR):
        notices.clear(notices.PRINT_ERROR, "the printer cleared its errors")


def _tell_arrival() -> None:
    """Someone has walked in: repeat what was announced to an empty room."""
    from core import announcements, quiet
    if quiet.is_in_sleep_hours():
        return
    for n in notices.pending():
        if n.kind in (notices.PRINT_DONE, notices.PRINT_ERROR):
            print(f"[eyes] Someone arrived; repeating {n.kind}.")
            announcements.announce(f"While you were away: {n.text}", priority=announcements.NOTICE,
                                   source=f"held {n.kind}", ping="wake_ping",
                                   then=lambda k=n.kind: notices.delivered(k))


def _loop() -> None:
    from core import display, mood, temperature
    bt = _bt_sink_present()
    was_present = present()
    uv_events = temperature.power_status().get("events", 0)
    tick = 0
    while True:
        try:
            if tick % 3 == 0:
                now_bt = _bt_sink_present()
                if now_bt and not bt:
                    print("[eyes] Bluetooth speaker connected.")
                    eyes.blip(es.Light(es.BT_BLUE, "double", 1.0), "left", 0.5)
                elif bt and not now_bt:
                    print("[eyes] Bluetooth speaker dropped.")
                    eyes.blip(es.Light(es.BT_BLUE, "fade", 1.0, period=1.0), "left", 1.0)
                bt = now_bt

            ev = temperature.power_status().get("events", 0)
            if ev > uv_events:
                eyes.blip(es.Light(es.AMBER, "flicker", 1.0), "both", 2.0)
            uv_events = ev

            _settle_printer_notices()
            is_present = present()
            if is_present and was_present is False:
                _tell_arrival()
            was_present = is_present

            eyes.set_mood_colour(display.mood_colour(mood.get()))
            eyes.set_status(*compose(gather(bt)))
        except Exception as e:
            print(f"[eyes] Status watch error: {e}")
        tick += 1
        time.sleep(TICK_SECS)


def start() -> None:
    """Begin watching. Presence also decides whether an announcement was heard."""
    notices.set_presence(present)
    threading.Thread(target=_probe_network, daemon=True, name="eye-net").start()
    threading.Thread(target=_loop, daemon=True, name="eye-watch").start()
