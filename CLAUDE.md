# Servoskull (Omega-7)

A voice assistant in a Warhammer 40k servo-skull prop on a Raspberry Pi 5: wake
word → Whisper → Claude with tools → ElevenLabs/Piper speech, plus a round GC9A01
"eye" display, camera, LEDs and an HTTPS web remote. On the unit it runs as the
`omega7` systemd service from `~/Servoskull` (`.venv/bin/python -m core.main`).

## Layout

- `core/` — the application. `main.py` is the orchestration loop (wake, record,
  transcribe, local intent handlers, `brain.respond`, speak); `brain.py` the Claude
  conversation and tool handlers; `tools_schema.py` the tool definitions; `llm.py`
  the API client (streaming, prompt caching); `display.py` the eye;
  `dice_faces.py` the symbols Necromunda's dice carry (a cross, a splintered
  burst, a skull, bullet holes, a crosshair, an arrow at any bearing), held as
  polygon geometry so `dice3d.py` can tumble them on the sides of a real cube
  and land it on the rolled face; `web.py` the web remote; `config.py` all
  settings.
- The web remote is one page: `web.py`'s `HTML_CLIENT` string (markup and all CSS)
  plus `core/app.js`. Omega-7's own views — the terminal, the memory bank, the
  setup wizard — are styled by the `.o7`/`.o7-modal` design system in that style
  block and use `o7-*` classes. The WFRP campaign view is inline-styled instead
  and inherits only the `:root` tokens, the global `button` rule and the body
  font, so those three stay as they are and new terminal styling goes under `.o7`.
  `app.js` reaches the markup by element id: keep the ids when rearranging it.
  Home-screen icons come from `generate_icons.py` into `core/static/`.
- `personalities/<key>/` — `persona.txt`, `config.json` (phrases, voice, wake-word
  model), `brain.py` (extra tools), `display.py`, screensavers. Omega-7's
  screensavers are one module each in `personalities/omega7/classic/` (green
  phosphor, shared `_phosphor.py`) and `lore/` (full colour, helpers in
  `_common.py`); each exposes `NAME` and `render(bezel, mask, now)` for the
  240×240 round panel at 30 FPS. Register new ones in the package `__init__.py`
  `_MODULES` list and update the counts in README.md.
- Omega-7's eye designs are one module each in `personalities/omega7/eyes/`
  (`cog` is the original), exposing `render_bezel()` and `render_frame(...)`;
  `personalities/omega7/display.py` delegates to the active one. The choice is
  switched by voice (`intents.eye_style`) and saved as `eye_style_<persona>.json`.
  Mood eyes declare `MOOD`. The "shuffle" style (the default) draws a new design
  on every return from a screensaver and on each mood change: the mood's own eye
  a third of the time, otherwise any other (`display.pick_eye_style`).
- `games/` — tabletop engines and rules: `wfrp/` (WFRP 4e game-master engine and
  Foundry bridge), `necromunda/` (Necromunda Skirmish), `bardstale/` (Apple IIe
  emulator agent), `netea/`, `netepic/`. Copyrighted rulebook text is built
  locally and git-ignored: most games use `games/ingest_pdf.py` to make a folder
  of Markdown, while `wfrp/` and `necromunda/` extract into SQLite instead
  (`rules_schema.py` + `extract/`), because their printed tables do not survive
  linear text extraction — an unprinted cell leaves no token and every later
  value shifts a column left. Rebuild Necromunda with
  `python -m games.necromunda.extract.ingest <core rulebook PDF>`; the database
  is reproducible, so it is dropped and rebuilt rather than migrated.
- `core/bt/` — Bluetooth as a desired state rather than a script. `model.py` is the
  data, `plan.py` the only place decisions are made (pure: given a snapshot and a
  desired state, the actions that close the gap), `bluez.py` BlueZ over its own
  D-Bus API via `dbus-fast`, and `manager.py` one owner — an asyncio loop on its own
  thread that applies the plan on every BlueZ signal and on a tick, so a speaker
  that drops is reconnected instead of staying dropped. Selected by
  `BLUETOOTH_BACKEND=dbus`; otherwise `core/bluetooth_ctrl.py` drives `bluetoothctl`
  through pexpect as before. That module stays the public face either way. The
  planner and the manager are tested against a fake bus, so no speaker is needed:
  `tests/test_bt_plan.py`, `tests/test_bt_manager.py`.
- A command's end is decided by `core/vad.py` (Silero VAD on onnxruntime) inside
  `audio.record()`; the recording is streamed to OpenAI's realtime transcription
  session by `transcribe.StreamingTranscriber` while it is captured, with the
  batch `transcribe()` as the fallback. `tests/fixtures/speech_22k.wav` is a real
  spoken sentence for testing either.
- Requests handled without the model (dice, Spotify, settings, confirmations) are
  matched by pure functions in `core/intents.py` and dispatched by the
  `_LOCAL_INTENTS` table in `core/main.py` to `_h_*` handlers. A new one needs a
  matcher, a handler, a table entry and tests in `tests/test_intents.py`.
- `tests/` — pytest unit tests for the pure-logic pieces (tracked even though the
  `test*` ignore rule covers scratch scripts).

## Conventions

- Python ≥ 3.10 syntax (`X | None`); the unit runs 3.13.
- Settings resolve environment → `settings.json` → default through
  `core/config.py`; every runtime file lives under `USER_DATA_DIR`
  (`~/.config/omega7`) via `config.data_path()`, never in the repo.
- No logging framework: `print("[module] message")`. The web transcript is built by
  parsing these, so keep the `[prefix]` form.
- Anything destructive or system-changing (update, reboot, shutdown, identity purge)
  goes through the spoken-confirmation flow in `main.py` (`request_maintenance`);
  a tool handler must never do it directly.
- A person's name used as a directory (`faces/`, `voices/`) must pass
  `config.identity_name()` first.
- Hardware modules no-op when their library is absent, so most of `core` imports on
  a Mac; `core.main` itself needs the Pi.
- Pillow's default font has no `—` or `∞`; use ASCII in on-screen text.

## Checks before shipping

- `python -m pytest tests` (a Python ≥ 3.10 venv with `pytest` and `python-dotenv`).
- `python -m pyflakes` and `python -m py_compile` on every file touched.
- New screensavers: render a full 5-minute showing (9000 frames) and time it; keep
  p95 under ~12 ms on the Pi 5.

## Deploy

Push to `main`, then on the unit: `cd ~/Servoskull && git pull --ff-only && sudo
systemctl restart omega7`, and watch `journalctl -u omega7 -f` for errors. The
voice-triggered self-update does the same plus `pip install -r requirements.txt`.
