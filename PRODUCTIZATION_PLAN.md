# Omega-7 Servo Skull — Productization Plan

Turning the single-tenant build into a replicable, consumer-friendly appliance.

## Decisions locked

- **Key model: bring-your-own-keys.** The buyer creates their own Anthropic / ElevenLabs / OpenAI accounts and enters keys in the on-device wizard. No backend, no billing, no per-user cost or liability for us. Everything runs on the Pi.
- **Polish level: full appliance.** Flashable SD image + Wi‑Fi hotspot provisioning + on-device web wizard. Unbox → power on → phone → done. No terminal, ever, for the customer.
- **Wizard stack:** small Flask/FastAPI app in the same repo, sharing `config.py`, run by its own systemd unit alongside the main loop.
- **Onboarding surface:** the skull hosts a local web portal (`http://omega7.local`). All keys, persona, and personalization happen there.

## Design principles

1. **Ship the product, not your instance.** The servo-skull *character* and hardware pinout are product data baked into the image. The owner's name, family, location, keys, and voice choice are per-user data written at setup and stored in a writable location — never in source, never in the image.
2. **Graceful degradation.** Piper (local TTS) is the default so the skull talks the moment a Claude key is entered. ElevenLabs and OpenAI/Whisper are optional upgrades. Only the Anthropic key is a hard blocker.
3. **Self-service diagnosis.** Every key field has a "Test" button that makes one cheap live call and shows pass/fail. This is the primary support-burden deflector for a BYO-keys product.
4. **Lean on existing tools for the Pi-hard parts.** Use a maintained captive-portal package for Wi‑Fi provisioning rather than hand-rolling AP/DHCP/DNS.

---

## Phase 1 — Config + persona + PII extraction (foundation)

**Goal:** Nothing else can be built until "the product" and "Sean's instance" are separated. This phase is a pure refactor, fully verifiable on the current hardware, and it also removes the PII currently compiled into source and JSON.

### 1.1 Introduce a writable user-config layer
- Define a config precedence: **baked defaults** (hardware pinout, thermal tuning for this build) → **user config** (keys, persona, voice, personalization) stored in a writable path outside the code tree (e.g. `~/.config/omega7/` or `/var/lib/omega7/`).
- Make `config.py` the single source of truth. Consolidate the stray direct `os.getenv` reads so the wizard controls everything:
  - `spotify_ctrl.py` — `SPOTIFY_CLIENT_ID/SECRET/REDIRECT_URI`
  - `cast_audio.py` — `GOOGLE_HOME_DEVICE`, `CAST_ENABLED`
  - `main.py` — `RESET_VOICE_CACHE`
  - `generate_sounds.py`, `generate_voice_training.py` — ElevenLabs vars (dev tools; lower priority but note them)
- Keep `.env` working for dev, but user config becomes the runtime source on the appliance.

### 1.2 Extract the persona from source
- Move the `SYSTEM_PROMPT` constant (`config.py:115-198`) out of Python into a shipped **persona template** (data file). This is the servo-skull character + tool-usage instructions — product data.
- Split the hardcoded "YOUR MASTER" PII block (name, birth year, city, family, employer, hobbies) into a separate **owner profile** the wizard writes. Inject it the same way `mood`/`memory` are already appended as `system_suffix` in `brain.py`.

### 1.3 Purge and reset personal data
- Remove the committed live `.env` and `.spotify_cache` from the repo/working tree.
- Ship `memory.json` and `longterm_memory.json` **empty**. The current files contain Sean's address, cat names, and an invented backstory — none of that ships.
- Add a factory-reset path that clears memory/mood/quiet/reminders/history for a clean per-unit state.

### 1.4 Verify
- Run the emulator and/or the Pi with a fresh empty user config + a test owner profile. Confirm persona loads, PII injection works, and no personal data leaks from source.

**Exit criteria:** No owner PII anywhere in source or shipped data. Persona is data. All config flows through one layer. Existing behavior unchanged on current hardware.

---

## Phase 2 — On-device setup wizard (web UI)

**Goal:** A non-technical buyer configures the whole skull from their phone browser.

### 2.1 Wizard service
- Small Flask/FastAPI app in the repo, its own systemd unit, sharing `config.py`. Serves on the LAN at `omega7.local`.
- Generate a **per-device admin password** at first boot (never a shared default). Show/announce it once; store its hash.

### 2.2 Key entry + live validation
- One field per provider with a **Test** button:
  - Anthropic — tiny `messages` call.
  - ElevenLabs — list voices.
  - OpenAI — list models.
- Green/red status inline. Mark Anthropic as required; ElevenLabs/OpenAI as optional with a note on what each unlocks.
- Write keys to the user-config store with restrictive file perms (`600`), off the boot partition.

### 2.3 Personalization surface
- **Owner profile**: name, how it should address you, location (for weather), people/interests — writes the Phase 1 owner profile.
- **Voice**: Piper (default, local, shipped) vs ElevenLabs (their key + voice ID) — plumbing already exists via `TTS_BACKEND`.
- **Wake word / name**: choose from a small menu of pre-trained `.onnx` wake words we ship (custom words require per-word training, so no free text).
- **Personality**: optional knob mapped onto the existing `mood` system.

### 2.4 Runtime controls (nice-to-have in this phase)
- Restart the skull service, view a status/health page, re-run a mic/audio device check from the browser (replaces manual `_miccheck.py`), factory reset.

### 2.5 Verify
- Fresh config → walk the wizard end to end on a phone → confirm keys persist, tests pass, persona/voice apply after a service restart.

**Exit criteria:** A person who has never used a terminal can fully configure and personalize the skull from a browser.

---

## Phase 3 — Wi‑Fi provisioning + flashable image (out-of-box)

**Goal:** The customer flashes once (or we pre-flash), powers on, and is guided from zero network to a working skull.

### 3.1 Wi‑Fi hotspot provisioning
- Integrate a maintained captive-portal tool (**Comitup** or Balena **wifi-connect**). First boot with no known network → skull raises its own AP → phone connects → pick home Wi‑Fi + password → hand off.
- After network hand-off, redirect/guide the user to the Phase 2 wizard at `omega7.local`.

### 3.2 Flashable SD image
- `pi_setup.sh` becomes the **image-build script**, not customer-run. Bake: venv + deps, Piper voice + wake-word models, both systemd units, the captive-portal tool, and a first-boot state that resets to hotspot mode with empty user config.
- Fix the currently hardcoded bits so the image is truly generic: Raspotify device name literal (`pi_setup.sh`), and Pi‑5-specific thermal thresholds if the hardware spec ever varies.
- Produce a versioned, reproducible image artifact.

### 3.3 First-boot lifecycle
- First boot: hotspot + wizard, empty config.
- Configured boot: normal skull operation.
- Factory reset (physical trigger or wizard button): back to first-boot state.

### 3.4 Physical + docs
- Printed quick-start card: power on → connect to "Omega-7-Setup" Wi‑Fi → follow phone → QR codes to each provider's API-key page.
- Rewrite `PI_SETUP_GUIDE.md` into a customer manual (the current one is a builder's guide).

### 3.5 Verify
- Flash a blank SD → boot a never-configured unit → phone-only path from hotspot through wizard to a talking, personalized skull. Test factory reset returns to clean state.

**Exit criteria:** A blank-SD unit reaches a fully personalized, talking skull with no terminal and no cable — phone only.

---

## Cross-cutting: security & hygiene (throughout)

- Per-device admin password; no shared defaults.
- User keys stored `600`, outside the boot partition, never in the image.
- No owner PII in source, shipped data, or the image (enforced starting Phase 1).
- Consider a pre-ship checklist / CI check that fails if `.env`, `.spotify_cache`, or non-empty memory files are present in the build.

## Sequencing summary

1. **Phase 1** — config/persona/PII extraction. Pure refactor, verify on current hardware. *Everything depends on this.*
2. **Phase 2** — web wizard (keys + tests + personalization). The core consumer surface.
3. **Phase 3** — hotspot provisioning + flashable image. The out-of-box moment; most Pi-specific, test last.

## Open items to decide later

- Exact writable-config path and format (dir of files vs single JSON/TOML).
- Which pre-trained wake words to ship in the selectable menu.
- Whether the wizard also exposes Spotify/Chromecast setup or leaves those as advanced/optional.
- Image distribution method (pre-flashed SD in the box vs downloadable image + Pi Imager instructions).
