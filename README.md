# Omega-7 — The Servo Skull Assistant

> *"This unit serves the Omnissiah, and, in its infinite mercy, you."*

An AI-powered **Warhammer 40,000 servo skull** that floats on your shelf, glares at you with glowing red optics, lights its own candles when it wakes, and answers you out loud — in character as an ancient, Emperor-devoted machine-spirit. It runs entirely on a **Raspberry Pi 5**, sees you through a camera, hears you through a mic, and speaks through a real voice. It knows the 40k rulebook cold, plays your music, monitors your 3D printer, simulates tabletop battles, and remembers who you are.

Point a wake word at it — *"Servitor"* — and it wakes, ignites its candle LEDs, pulses its iris in time with its speech, and responds.

<p align="center">
  <img src="images/cog_eye_preview.png" width="320" alt="The machine-spirit eye — glowing red iris with the Mechanicus tick-ring">
</p>

---

## What it does

Omega-7 is a self-contained voice assistant with a very specific soul. Everything runs **on the Pi itself** — the only things that leave the device are the API calls you opt into (Claude for the brain, optionally OpenAI Whisper for transcription, optionally ElevenLabs for the voice).

- **🗣️ Talks back, in character.** Wake it with *"Servitor"* and it listens, thinks (Anthropic Claude), and replies aloud through a text-to-speech voice — formal, archaic, ominous, devoted to the Emperor and the Machine God. It refers to itself as "this unit" and speaks with serialized, uninterrupted canned response playback.
- **👁️ Sees you.** An Arducam IMX708 camera lets it describe the scene on demand — *"What do you see, Omega-7?"* — and, with the optional time-of-flight proximity sensor, it can wake and greet you when you physically approach, even in the dark.
- **💡 Physical reactions & AdMech Eye HUD.** Three red LEDs behind the eye lenses and a circular GC9A01 IPS panel "machine-spirit eye" pulse in time with its speech. Candle LEDs atop the skull light when it wakes and snuff on shutdown. The display features 6 dynamic HUD animation states:
  * **Praise the Omnissiah Logo**: Off-white bone and machine grey AdMech skull-cog vector rendering expanding on boot/update.
  * **Auspex Scan**: Concentric Noosphere beacon pulsing waves mapping surroundings.
  * **Targeting lock-on**: A floating crosshair tracking target focus during vision queries.
  * **Equalizer visualizer**: Dynamic frequency bars bouncing to Spotify Connect streams.
  * **Cogitation gear**: Rotating bezel cog wheel spinning at 80 deg/sec during brain processing.
  * **Vector Digit projector**: High-tech segment lines drawing actual dice values.
  * **Artwork Projector**: Direct DeviantArt RSS search fetching and displaying 40k or Necromunda fan art inside the mechanical lens aperture.
- **📖 Knows the rules.** A built-in, offline rules library lets it answer questions about **Warhammer 40,000 (11th ed.)**, **Necromunda**, **NetEpic (Epic 2nd ed.)**, and **Net Epic Armageddon (Epic 3rd ed.)** — datasheets, stratagems, weapons, points, formations, tournament rules — quoting the actual rulebooks rather than guessing.
- **🎲 Tabletop Game Context & specialized dice simulator.** Persistent memory tracks what game is active (**Necromunda**, **NetEpic**, **NetEA**, **Warhammer 40k**). Zero-latency regex intercepts roll specialized dice (firepower, injury, scatter, combat resolution, macro-weapons, saving throws) instantly, playing rolling dice sound effects and projecting vector-drawn alphanumeric outcomes directly on the eye screen.
- **🖨️ Bambu Lab 3D Printer Monitor.** Subscribes to local secure MQTT broker telemetry. Verbally reports print start/completion, reads temperature stats, and issues warning announcements if the printer hits a Health Management System (HMS) diagnostic fault code.
- **🎵 Plays your music.** Spotify voice control — "play the Imperial march" — with pause/resume/skip, routed through its own speaker or a Bluetooth speaker it can discover and pair with.
- **🧠 Remembers you.** Short- and long-term memory, a drifting mood/personality state, timers & reminders, and a proactive daily briefing (weather + news) the first time you wake it each morning.
- **🌡️ Looks after itself.** Monitors its own core temperature and warns you if it runs hot. Volume control and a "silent mode" for its unprompted idle observations round it out.
- **🔊 Atmosphere.** Mechanicus chimes and vox-crackle stings play on wake and before it speaks.

It's a **bring-your-own-keys** device: you supply your own Anthropic (and optional OpenAI / ElevenLabs / Spotify) accounts, and everything else lives on the Pi. No backend, no subscription, no data leaving the device beyond the model calls you choose to make.

---

## Where it's headed — the productized vision

Today Omega-7 is a builder's project: you wire it, flash a Pi, edit a `.env`, and run it from a terminal. The [**Productization Plan**](PRODUCTIZATION_PLAN.md) turns it into an **unbox-and-go appliance**. When that's done, the experience becomes:

1. **Power it on.** No keyboard, no HDMI, no terminal — ever.
2. **Connect your phone** to the skull's own Wi-Fi hotspot (`Omega-7-Setup`). A captive portal appears; you pick your home Wi-Fi and hand off.
3. **Open the setup wizard** at `http://omega7.local` in your phone browser. There you:
   - Paste your **Anthropic key** (required) and optional **OpenAI / ElevenLabs / Spotify** keys — each with a **Test** button that makes one live call and shows green/red so you know it works before you leave the page.
   - Fill in an **owner profile** — your name, how it should address you, your location (for weather), the people and things it should know about — so it greets *you*, personally.
   - Pick a **voice** (local Piper, shipped and free, or a cloud ElevenLabs voice), a **wake word** from a menu, and a **personality** slant.
4. **It comes alive.** After a restart it's a fully personalized, talking, seeing servo skull — configured entirely from your phone.

Plus runtime controls from the browser: restart it, check its health, re-run a mic/audio check, or factory-reset it back to a clean out-of-box state. Every unit gets its own admin password (never a shared default), keys are stored locked-down and off the boot partition, and **no personal data is ever baked into the software** — the *character* ships, your data is written at setup.

See [PRODUCTIZATION_PLAN.md](PRODUCTIZATION_PLAN.md) for the full phased roadmap (config/PII separation → web wizard → Wi-Fi provisioning + flashable SD image).

---

## Build it from scratch

Two documents carry the full build. Start with the shopping list, then follow the setup guide end to end.

### 1. Get the parts — [`SHOPPING_LIST.txt`](SHOPPING_LIST.txt)

The complete bill of materials, with specific recommended products and why each one matters. The highlights:

| Group | What you need |
|---|---|
| **Body** | The **[Servo Skull — LED Candlelit Lantern 3D model](https://www.printables.com/model/1457078-servo-skull-led-candlelit-lantern)** — the printable chassis this build is designed around |
| **Core** | Raspberry Pi 5 (4 GB), official Active Cooler, 64 GB microSD, **27 W** USB-C PD supply (the Pi 5 *requires* it — underpowering causes crashes) |
| **Audio** | UGREEN USB sound card, mini speakers, a 3.5 mm electret/lavalier mic for the nasal cavity |
| **Vision** | Arducam IMX708 Wide camera (12 MP, autofocus, includes the Pi 5 CSI adapter) |
| **Eyes** | 3× 5 mm red LEDs + 3× 220 Ω resistors + jumper wires + a mini breadboard/perfboard |
| **Display** | GC9A01 1.28" round IPS panel (240×240, SPI) |
| **Sensors** | *(optional)* VL53L1X time-of-flight proximity sensor for approach detection |
| **Candles** | Self-flickering LED candle bulbs for the top of the skull |
| **Setup-only** | micro-HDMI→HDMI cable + USB keyboard (borrow if needed) for first boot |

Approximate hardware cost is **~$157** for the electronics (excluding the printed skull, candles, and any props you already own). You'll also want your own **Anthropic API key** (required; Claude Haiku is used, pay-per-token, very cheap) and optionally **OpenAI** (Whisper STT), **ElevenLabs** (premium cloud voice), and **Spotify Premium** (music control).

### 2. Assemble & install — [`PI_SETUP_GUIDE.md`](PI_SETUP_GUIDE.md)

A start-to-finish, matched-to-the-code guide. Its ten steps:

1. **Install the Active Cooler** first, board unpowered (the Pi 5 throttles without it).
2. **Flash the microSD** with Raspberry Pi OS 64-bit (Debian *Trixie*) using Pi Imager — pre-set the hostname `omega7`, your user, Wi-Fi, and SSH.
3. **First boot & base config** — update the OS and enable the SPI bus the round display needs.
4. **Wiring** — a fully annotated GPIO pinout with per-subsystem diagrams for the eye LEDs, the GC9A01 display, the camera ribbon, the USB audio, the optional proximity sensor, and the transistor-switched candle LEDs. Includes a pre-power-on sanity checklist. *(All wiring done with the Pi off and unplugged.)*
5. **Deploy the software** — clone the repo to `~/skull`, copy in your `.env`, and run the one-shot `pi_setup.sh` installer (system packages, Python venv, Piper voice + wake-word models, and both the `omega7` and `raspotify` systemd services). Includes the essential Pi 5 `RPi.GPIO` shim step.
6. **Configure `.env`** — the audio, display, camera, proximity, and candle settings, with the PipeWire routing that makes voice and music share one speaker cleanly.
7. **Bring-up tests** — verify each subsystem one at a time (eyes, display, camera, mic/speaker) before final assembly.
8. **Run it** — manually to watch the logs, then as the auto-starting service so the finished skull is a headless appliance that wakes on its own.
9. **Troubleshooting** — a symptom→fix table for the problems you're actually likely to hit.
10. **Final assembly** — mounting the camera, display, LEDs, and mic inside the printed skull.

> **Golden rule from the guide:** do *all* wiring with the Pi powered off and unplugged.

---

## Repository layout

```
skull/                 The application (Python package)
  main.py              Wake-word loop + orchestration
  brain.py             Claude conversation + tool dispatch
  llm.py               Anthropic client
  wake_word.py         openWakeWord ("Servitor")
  transcribe.py        Speech-to-text (Whisper)
  tts.py               Text-to-speech (Piper / ElevenLabs)
  audio.py             Capture & playback (PipeWire)
  camera.py            IMX708 vision
  proximity.py         VL53L1X time-of-flight trigger
  eyes.py              Red eye LEDs (GPIO)
  display.py           GC9A01 round "machine-spirit eye"
  candles.py           Candle LEDs (transistor-switched GPIO)
  spotify_ctrl.py      Music control
  bambu_ctrl.py        Bambu Lab 3D printer secure MQTT client
  bluetooth_ctrl.py    Bluetooth speaker pairing
  search.py            Weather / news / rules lookups
  memory.py mood.py    Persistent memory & personality state
  reminders.py quiet.py temperature.py sfx.py cast_audio.py
  persona_template.txt The servo-skull character (product data)
  config.py            Pin assignments + settings (single source of truth)

emulator/              Run the skull on your Mac/Windows without hardware
Rules/                 Offline rules library ingestion (40k / Necromunda / NetEpic / NetEA)
pi_setup.sh            One-shot Pi installer / image-build script
omega7.service         systemd unit for the main loop
SHOPPING_LIST.txt      Bill of materials
PI_SETUP_GUIDE.md      Build & install guide
PRODUCTIZATION_PLAN.md Roadmap to an unbox-and-go appliance
```

There's also an **emulator** (`emulator/`, `run_emulator.py`) so you can develop and test the personality, tools, and conversation flow on a Mac or Windows machine — no Pi or wiring required.

---

## Requirements at a glance

- **Hardware:** Raspberry Pi 5 (4 GB) + the parts in [`SHOPPING_LIST.txt`](SHOPPING_LIST.txt), inside the [printed skull](https://www.printables.com/model/1457078-servo-skull-led-candlelit-lantern).
- **OS:** Raspberry Pi OS 64-bit (Debian *Trixie*, Python 3.13, PipeWire audio).
- **Keys:** Anthropic (required); OpenAI, ElevenLabs, Spotify (optional, each unlocks a feature).
- **Default voice:** Piper, local and free — the skull talks the moment a Claude key is entered. ElevenLabs and OpenAI/Whisper are optional upgrades.

---

*The Omnissiah smiles upon a clean install. Praise the Machine God.*
