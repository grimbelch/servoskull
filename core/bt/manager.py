"""One owner of the Bluetooth state: an asyncio loop on its own thread.

Being the only writer is what makes concurrent commands safe. Two voice commands
arriving together -- "connect the JBL" and "disconnect everything" -- are two
coroutines on one loop, applied in the order they were submitted, so there is no
lock to remember and no interleaving to get wrong. The old implementation had
three independent pexpect sessions that could run at once and race on the default
sink.

Reconciling happens on every BlueZ signal and on a periodic tick, so a speaker
that drops is noticed within the tick rather than never.
"""

from __future__ import annotations

import asyncio
import threading
import time

from core.bt import audio_route
from core.bt.bluez import BluezBus, BluezUnavailable
from core.bt.model import Action, Desired, Outcome, Snapshot
from core.bt.plan import plan

TICK_SECS = 20.0            # the floor on noticing something nobody told us about
MAX_STEPS = 8               # a reconcile applies at most this many actions
SETTLE_SECS = 6.0           # how long to let BlueZ and PipeWire catch up
# Connecting a speaker that is switched off or out of range does not fail fast, and
# BlueZ may return from Connect() without the link coming up. Driving the real
# speaker showed the reconciler calling connect three times in one pass and blowing
# its own deadline. So a slow action that has just FAILED is left alone for a while,
# and the wait grows the longer it keeps failing -- a speaker switched off for the
# afternoon should be tried every couple of minutes, not every twenty seconds.
#
# Only failures count. A connect that succeeded and later dropped is reconnected at
# once, because that is the case this whole package exists for.
SLOW_ACTIONS = frozenset({"connect", "pair", "route"})
BACKOFF_SECS = (10.0, 20.0, 40.0, 80.0, 120.0)
# How long any single BlueZ call may take before it is abandoned. Connect() on a
# speaker that is switched off does not return promptly -- measured against the real
# one, it outlasted a 45-second deadline without raising -- so the owner puts its own
# limit on every call rather than trusting the other side to be quick. A timeout is
# a failure like any other and feeds the backoff.
ACTION_TIMEOUTS = {"connect": 25.0, "pair": 30.0, "disconnect": 10.0}
DEFAULT_ACTION_TIMEOUT = 10.0


def _state_path():
    from core import config
    return config.data_path("bluetooth.json")


def load_desired() -> Desired:
    """The speaker we were last asked for, across restarts.

    Held only in memory, "the speaker that dropped at three in the morning is
    reconnected" would stop at a service restart -- and a restart is exactly when a
    link is most likely to be gone.
    """
    import json
    try:
        saved = json.loads(_state_path().read_text())
        return Desired(speaker=(saved.get("speaker") or None))
    except Exception:
        return Desired()


def save_desired(desired: Desired) -> None:
    import json
    from core import config
    try:
        config.atomic_write(_state_path(),
                            json.dumps({"speaker": desired.speaker}))
    except Exception as e:
        print(f"[bt] Could not remember the desired speaker: {e}")


def remembered_speaker() -> str | None:
    """The speaker to converge on at boot, without starting anything."""
    return load_desired().speaker


class BluetoothManager:
    """Owns the adapter. All public methods are safe to call from any thread."""

    def __init__(self, bus=None, tick_secs: float = TICK_SECS,
                 settle_secs: float = SETTLE_SECS):
        self._bus = bus if bus is not None else BluezBus()
        self._tick = tick_secs
        self._settle = settle_secs
        self._loop: asyncio.AbstractEventLoop | None = None
        self._thread: threading.Thread | None = None
        self._desired = load_desired()
        self._wake = None               # set on the loop; nudges the reconciler
        self._last: Snapshot | None = None
        self._started = threading.Event()
        self._fatal: str | None = None
        # (kind, mac) -> (when it last failed, how many times in a row)
        self._failures: dict[tuple[str, str], tuple[float, int]] = {}
        self._gate = None               # one reconcile at a time; created on the loop

    # ── lifecycle ─────────────────────────────────────────────────────────────

    def start(self, timeout: float = 10.0) -> bool:
        """Bring the loop up. False if BlueZ could not be reached."""
        if self._thread is not None:
            return self._fatal is None
        self._thread = threading.Thread(target=self._run, name="bluetooth",
                                        daemon=True)
        self._thread.start()
        self._started.wait(timeout)
        if self._fatal:
            print(f"[bt] Bluetooth manager unavailable: {self._fatal}")
            return False
        return True

    def stop(self) -> None:
        loop = self._loop
        if loop is None:
            return
        loop.call_soon_threadsafe(loop.stop)
        if self._thread:
            self._thread.join(timeout=3)

    def _run(self) -> None:
        self._loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self._loop)
        try:
            self._loop.run_until_complete(self._boot())
        except BluezUnavailable as e:
            self._fatal = str(e)
            self._started.set()
            return
        except Exception as e:
            self._fatal = f"{type(e).__name__}: {e}"
            self._started.set()
            return
        self._started.set()
        try:
            self._loop.run_forever()
        finally:
            self._drain()
            self._loop.close()

    def _drain(self) -> None:
        """Cancel what is still running and let it finish, then close the bus."""
        try:
            pending = [t for t in asyncio.all_tasks(self._loop) if not t.done()]
            for task in pending:
                task.cancel()
            if pending:
                self._loop.run_until_complete(
                    asyncio.gather(*pending, return_exceptions=True))
        except Exception:
            pass
        try:
            self._loop.run_until_complete(self._bus.close())
        except Exception:
            pass

    async def _boot(self) -> None:
        await self._bus.connect_bus()
        self._wake = asyncio.Event()
        # Being the only THREAD is not being the only task: the periodic reconcile
        # and a submitted command are two coroutines on this one loop, and driving
        # the real speaker showed them interleaving -- three Connect() calls in
        # flight at once, which is the race this design was supposed to remove.
        self._gate = asyncio.Lock()
        # A BlueZ signal is a reason to reconcile at once rather than at the tick.
        self._bus.on_change(lambda: self._loop.call_soon_threadsafe(self._wake.set))
        self._loop.create_task(self._reconcile_loop())

    # ── the loop ──────────────────────────────────────────────────────────────

    async def _reconcile_loop(self) -> None:
        while True:
            try:
                await self._reconcile_once()
            except asyncio.CancelledError:
                return                      # shutting down; go quietly
            except Exception as e:
                print(f"[bt] Reconcile error: {e}")
            try:
                await asyncio.wait_for(self._wake.wait(), timeout=self._tick)
            except asyncio.TimeoutError:
                pass
            except asyncio.CancelledError:
                return
            self._wake.clear()

    async def _snapshot(self) -> Snapshot:
        """BlueZ's view, plus where the audio actually is."""
        snap = await self._bus.snapshot()
        wanted = self._desired.speaker
        snap = Snapshot(
            powered=snap.powered, discovering=snap.discovering,
            devices=snap.devices, adapter_path=snap.adapter_path,
            sink=audio_route.current_sink_for(wanted),
            default_sink=audio_route.default_sink(),
        )
        self._last = snap
        return snap

    async def _reconcile_once(self) -> Outcome:
        """Apply the plan until it is empty, re-snapshotting between actions.

        Serialised: a second caller waits rather than acting on a snapshot the
        first is already changing.
        """
        async with self._gate:
            return await self._reconcile_locked()

    async def _reconcile_locked(self) -> Outcome:
        out = Outcome()
        for _ in range(MAX_STEPS):
            now = time.monotonic()
            snap = await self._snapshot()
            steps = plan(snap, self._desired, now=now)
            if not steps:
                return out
            action = steps[0]
            key = (action.kind, action.mac)
            wait = self._backoff_remaining(key, now)
            if wait > 0:
                out.fail(action, f"failed recently; next attempt in {wait:.0f}s")
                return out
            ok, why = await self._apply(action)
            if ok:
                out.note(action)
                self._failures.pop(key, None)
            else:
                self._note_failure(key, time.monotonic())
                out.fail(action, why)
                return out
            if self._settle and action.kind in ("connect", "disconnect", "power_on"):
                await asyncio.sleep(self._settle)
                # Say what actually happened, rather than assuming the call worked.
                if action.kind == "connect":
                    dev = (await self._bus.snapshot()).device(action.mac)
                    if not (dev and dev.connected):
                        # Connect() can return without the link coming up, so the
                        # result is checked rather than assumed.
                        self._note_failure(key, time.monotonic())
                        out.fail(action, "BlueZ returned but the link did not come "
                                         "up; the speaker may be off or out of range")
                        return out
        return out

    def _backoff_remaining(self, key, now: float) -> float:
        """Seconds still to wait before retrying `key`, or 0 to go ahead."""
        if key[0] not in SLOW_ACTIONS:
            return 0.0
        last = self._failures.get(key)
        if last is None:
            return 0.0
        when, count = last
        wait = BACKOFF_SECS[min(count, len(BACKOFF_SECS)) - 1]
        return max(0.0, wait - (now - when))

    def _note_failure(self, key, now: float) -> None:
        _, count = self._failures.get(key, (0.0, 0))
        self._failures[key] = (now, count + 1)

    async def _apply(self, action: Action) -> tuple[bool, str]:
        print(f"[bt] {action}")
        limit = ACTION_TIMEOUTS.get(action.kind, DEFAULT_ACTION_TIMEOUT)
        try:
            return await asyncio.wait_for(self._apply_now(action), timeout=limit)
        except asyncio.TimeoutError:
            return False, f"no answer from BlueZ within {limit:.0f}s"
        except Exception as e:
            # org.bluez.Error.* arrives here with a reason, where pexpect gave a
            # timeout that said nothing about why.
            return False, f"{type(e).__name__}: {e}"

    async def _apply_now(self, action: Action) -> tuple[bool, str]:
        try:
            if action.kind == "power_on":
                await self._bus.power_on()
            elif action.kind == "trust":
                await self._bus.set_trusted(action.mac, True)
            elif action.kind == "connect":
                await self._bus.connect(action.mac)
            elif action.kind == "disconnect":
                await self._bus.disconnect(action.mac)
            elif action.kind == "start_discovery":
                await self._bus.start_discovery()
            elif action.kind == "stop_discovery":
                await self._bus.stop_discovery()
            elif action.kind == "route":
                if not audio_route.set_default_sink(action.detail):
                    return False, "pactl refused the sink"
                audio_route.pin_voice_to_internal()
            elif action.kind == "unroute":
                sink = audio_route.internal_sink()
                if sink and not audio_route.set_default_sink(sink):
                    return False, "pactl refused the internal sink"
                audio_route.pin_voice_to_internal()
            else:
                return False, f"unknown action {action.kind}"
            return True, ""
        except asyncio.CancelledError:
            raise

    # ── the public, thread-safe surface ───────────────────────────────────────

    def _submit(self, coro, timeout: float):
        if self._loop is None or self._fatal:
            raise BluezUnavailable(self._fatal or "manager not started")
        fut = asyncio.run_coroutine_threadsafe(coro, self._loop)
        return fut.result(timeout=timeout)

    def set_speaker(self, mac: str | None, timeout: float = 120.0) -> Outcome:
        """Declare which speaker should be connected, and converge on it."""
        self._desired = self._desired.with_speaker(mac)
        save_desired(self._desired)
        print(f"[bt] Desired speaker: {self._desired.speaker or 'none'}")
        return self._submit(self._reconcile_once(), timeout)

    def discover(self, seconds: float = 6.0, timeout: float = 30.0) -> Snapshot:
        """Run discovery for `seconds`, then return everything known."""
        import dataclasses
        self._desired = dataclasses.replace(
            self._desired, discovering_until=time.monotonic() + seconds)
        self._submit(self._reconcile_once(), timeout)
        time.sleep(seconds)
        snap = self._submit(self._snapshot(), timeout)
        self._desired = dataclasses.replace(self._desired, discovering_until=0.0)
        self._submit(self._reconcile_once(), timeout)
        return snap

    def snapshot(self, timeout: float = 15.0) -> Snapshot:
        return self._submit(self._snapshot(), timeout)

    def reconcile(self, timeout: float = 45.0) -> Outcome:
        return self._submit(self._reconcile_once(), timeout)

    @property
    def desired(self) -> Desired:
        return self._desired

    @property
    def available(self) -> bool:
        return self._loop is not None and not self._fatal
