# Servoskull (Omega-7)

A voice assistant in a Warhammer 40k servo-skull prop on a Raspberry Pi 5: wake
word → Whisper → Claude with tools → ElevenLabs/Piper speech, plus a round GC9A01
"eye" display, camera, LEDs and an HTTPS web remote. On the unit it runs as the
`omega7` systemd service from `~/Servoskull` (`.venv/bin/python -m core.main`).

## Layout

- `core/` — the application. `main.py` is the orchestration loop (wake, record,
  transcribe, local intent handlers, `brain.respond`, speak); `brain.py` the Claude
  conversation and tool handlers; `tools_schema.py` the tool definitions; `llm.py`
  the API client (streaming, prompt caching); `display.py` the eye; `web.py` the
  web remote; `config.py` all settings.
- `personalities/<key>/` — `persona.txt`, `config.json` (phrases, voice, wake-word
  model), `brain.py` (extra tools), `display.py`, screensavers. Omega-7's
  screensavers are one module each in `personalities/omega7/classic/` (green
  phosphor, shared `_phosphor.py`) and `lore/` (full colour, helpers in
  `_common.py`); each exposes `NAME` and `render(bezel, mask, now)` for the
  240×240 round panel at 30 FPS. Register new ones in the package `__init__.py`
  `_MODULES` list and update the counts in README.md.
- `games/` — tabletop engines and rules: `wfrp/` (WFRP 4e game-master engine and
  Foundry bridge), `bardstale/` (Apple IIe emulator agent), `netea/`, `netepic/`.
  Copyrighted rulebook text is built locally with `games/ingest_pdf.py` and
  git-ignored.
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
  the average under ~5 ms and p95 under ~12 ms on the Pi 5.

## Deploy

Push to `main`, then on the unit: `cd ~/Servoskull && git pull --ff-only && sudo
systemctl restart omega7`, and watch `journalctl -u omega7 -f` for errors. The
voice-triggered self-update does the same plus `pip install -r requirements.txt`.
