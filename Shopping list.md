# Omega-7 Servo Skull — Shopping List & Bill of Materials

Warhammer 40k AI Talking Servo Skull Build based on Raspberry Pi 5.

---

## 1. 3D Printed Body
- [ ] **Servo Skull — LED Candlelit Lantern (3D model / STL)**
  - [Printables Model Link](https://www.printables.com/model/1457078-servo-skull-led-candlelit-lantern) (Google Drive backup: https://drive.google.com/drive/folders/14fDHrc1rdDoB-aAqmKuZd4EoFfS8hWga?usp=sharing)
  - The printable skull chassis this entire build is designed around.
  - Houses the eye LEDs, GC9A01 round display, camera module, nasal mic capsule, rangefinder, and candle LEDs.
  - Print in your filament of choice (bone/ivory PLA with an acrylic wash reads best for 40k lore).

---

## 2. Core Computing
- [x] **Raspberry Pi 5 (4GB RAM recommended)**
  - Pi 5 is faster than Pi 4; 8GB is available but unnecessary for this project.
- [x] **MicroSD Card (32GB minimum, 64GB recommended, Class 10 / U3)**
  - 64GB recommended for audio cache, speech models, and log files.
- [x] **iUniker 27W PD USB-C Power Supply (ASIN: B0FHH9K47T)**
  - 5.1V @ 5A, GaN, marketed specifically for Raspberry Pi 5.
  - **CRITICAL:** Pi 5 REQUIRES 27W PD; underpowering causes random system crashes and brownouts.
- [x] **Raspberry Pi 5 Active Cooler (Official)**
  - Low-profile fan + heatsink combo designed specifically for Pi 5.
  - Pi 5 will thermally throttle inside an enclosed skull without active cooling.

---

## 3. Audio — Input & Output
- [x] **UGREEN USB External Sound Card (ASIN: B01N905VOY)**
  - Provides 3.5mm headphone output (→ powered speakers) and 3.5mm mic input (→ nasal mic).
  - USB Audio Class compliant — plug-and-play on Linux with zero custom driver setup.
  - Set `AUDIO_OUTPUT_DEVICE` and `MIC_DEVICE_INDEX` in `.env` to its ALSA device index.
- [x] **XMSJSIY Mini Computer Speakers (ASIN: B0D7L5JQJC)**
  - USB-powered (can run off Pi USB port), 3.5mm audio input, built-in volume control knob.
  - Stereo pair; mount one inside/behind skull chassis or run mono.
- [x] **3.5mm Electret Condenser Mic Capsule (Lavalier / tie-clip type)**
  - Mounted inside nasal cavity; plugs into UGREEN mic jack.
  - Standard 3.5mm TRS plug.

---

## 4. Camera — Vision
- [x] **Arducam IMX708 Wide Camera Module (ASIN: B0C5D97DRJ)**
  - Sony IMX708 sensor, 12MP, 120° FOV, autofocus.
  - Includes CSI ribbon cable with 15-to-22 pin adapter (Pi 5 ready out-of-the-box).
  - Mounts directly inside skull eye socket; supported by native `picamera2` driver on Pi OS.
  - Activate by setting `CAMERA_ENABLED=true` in `.env`.

---

## 5. Eye LEDs & Displays (GPIO Controlled)
- [x] **EDGELEC 5mm Red Diffused LEDs (ASIN: B077X95F7C) — 3x used**
  - Controlled via GPIO pins 22, 23 & 27.
  - *Note:* Do NOT use the included 6–12V resistors with Pi 3.3V GPIO header pins.
- [x] **220-ohm Resistors x3**
  - Current-limiting resistors for 3.3V GPIO pins.
- [x] **GC9A01 1.28" Round IPS Display (240x240, SPI)**
  - Eye display screen driven via SPI (`/dev/spidev0.0`).
- [x] **Jumper Wires (Male-to-Female, 10cm / 20cm)**
  - For connecting Pi 5 40-pin GPIO header to LED circuit and display.
- [ ] **Mini Breadboard / Perfboard**
  - For mounting the LED + resistor circuit neatly inside the skull.

---

## 6. Proximity Sensor — Laser Rangefinder
- [ ] **VL53L1X Time-of-Flight (ToF) Laser Rangefinder Sensor**
  - Measures physical presence/distance up to ~4m/8m using eye-safe laser flight time over I2C.
  - Connects via I2C: VCC (3.3V Pin 1), GND (Pin 9), SDA (GPIO 2 / Pin 3), SCL (GPIO 3 / Pin 5).
  - Supported out-of-the-box in `skull/proximity.py` and `skull/camera.py` via `python-VL53L1X`.
- [ ] **4-pin Dupont Ribbon Cable (Female-to-Female, 20–30cm)**
  - Routes from rangefinder module through skull to GPIO header inside.
  - JST-XH 4-pin connector kit is a tidier alternative for a locking plug.

---

## 7. Candle LEDs (Top of Skull)
- [x] **Self-Flickering LED Candle Bulbs (E10 or bare LED type)**
  - Hardware flicker effect built-in — no Pi control logic required.
  - Warm white or amber for authentic Tech-Priest candle aesthetic.

---

## 8. Wiring & Assembly Consumables
- [x] **Heat Shrink Tubing Assortment** — for insulating LED leads
- [x] **Electrical Tape**
- [x] **Thin Gauge Wire (22–26 AWG)** — for routing inside skull
- [x] **Zip Ties / Adhesive Cable Clips** — for cable management
- [x] **Hot Glue Gun + Sticks** — for securing components inside skull

---

## 9. Initial Setup (One-Time / Borrowable)
- [x] **Micro-HDMI to HDMI Adapter or Cable** — for initial Pi OS display setup
- [x] **USB Keyboard** — for initial Pi OS console configuration

---

## 10. Networking
- [x] **Wi-Fi** — built into Pi 5 (no extra hardware needed)
- [ ] **Ethernet Cable** (optional fallback if initial Wi-Fi setup is tricky)

---

## 11. Software & API Accounts (No Hardware Cost)
- [x] **Anthropic API Key** — [console.anthropic.com](https://console.anthropic.com)
  - Powers the Claude brain; pay-per-token API.
- [x] **OpenAI API Key** — [platform.openai.com](https://platform.openai.com)
  - Used for Whisper speech-to-text transcription.
- [x] **ElevenLabs Account** (OPTIONAL) — [elevenlabs.io](https://elevenlabs.io)
  - Optional cloud TTS voice (project defaults to Piper local TTS for free offline voice).
- [x] **Spotify Premium Account** (OPTIONAL) — [spotify.com](https://spotify.com)
  - Required for Spotify voice control feature (requires free app registered at [developer.spotify.com](https://developer.spotify.com)).

---

## 12. Already Owned Items
- [x] 3D printed skull chassis
- [x] Red binocular eye lenses
- [x] Mechanical tentacle arm
- [x] Self-flickering candle LEDs (installed)
- [x] OpenWakeWord custom model (`models/servitor.onnx`)

---

## 13. Approximate Total Cost (Hardware Only)
| Item | Approx Cost |
|---|---|
| Raspberry Pi 5 (4GB) | ~$50 |
| Pi 5 Active Cooler | ~$5 |
| MicroSD 64GB | ~$12 |
| USB-C Power Supply (27W) | ~$12 |
| UGREEN USB Sound Card | ~$10 |
| XMSJSIY Mini Speakers | ~$20 |
| Lavalier Mic Capsule | ~$8 |
| Arducam IMX708 Camera | ~$30 |
| VL53L1X Laser Rangefinder | ~$10 |
| LEDs, Resistors, Wires, Consumables | ~$10 |
| **Total Approximate Cost** | **~$167 USD** |

*(Excludes skull print, eye lenses, candle LEDs, and tentacle arm which were already owned.)*
