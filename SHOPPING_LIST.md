# Omega-7 Servo Skull — Shopping List

Build requirements for the Warhammer 40k AI Talking Servo Skull based on Raspberry Pi 5.

---

## 3D Printed Body
- [ ] **Servo Skull — LED Candlelit Lantern (3D model / STL)**
  - [Printables Link](https://www.printables.com/model/1457078-servo-skull-led-candlelit-lantern)
  - The printable skull chassis this build is designed around.
  - Houses the eye LEDs, round display, camera, mic, rangefinder, and candle LEDs.

---

## Core Computing
- [x] **Raspberry Pi 5 (4GB RAM recommended)**
  - 8GB is available but unnecessary for this project.
- [x] **MicroSD Card (32GB minimum, 64GB recommended, Class 10 / U3)**
  - 64GB recommended for audio cache and models.
- [x] **27W PD USB-C Power Supply (5.1V @ 5A GaN)**
  - Pi 5 REQUIRES 27W; underpowering causes instability and random crashes.
- [x] **Raspberry Pi 5 Active Cooler (Official)**
  - Keeps Pi 5 thermal throttling under control in enclosed skull.

---

## Audio (Input & Output)
- [x] **UGREEN USB External Sound Card**
  - Provides 3.5mm mic input and 3.5mm headphone/speaker output.
  - Plug-and-play USB Audio Class on Linux.
- [x] **XMSJSIY Mini Computer Speakers**
  - USB-powered speaker pair; mount inside/behind skull chassis.
- [x] **3.5mm Electret Condenser Mic Capsule (Lavalier / tie-clip type)**
  - Mounted in nasal cavity; plugs into sound card input.

---

## Camera (Vision)
- [x] **Arducam IMX708 Wide Camera Module**
  - Sony IMX708 12MP, 120° FOV, autofocus.
  - Includes 15-to-22 pin CSI ribbon adapter for Pi 5.
  - Pre-installed `picamera2` support on Pi OS.

---

## Eye LEDs & Displays
- [x] **EDGELEC 5mm Red Diffused LEDs (3x required)**
  - GPIO controlled (pins 22, 23 & 27).
- [x] **220-ohm Resistors (3x required)**
  - Current-limiting resistors for 3.3V GPIO header pins.
- [x] **GC9A01 1.28" Round IPS Display (240x240, SPI)**
  - Eye display screen driven via SPI.
- [x] **Jumper Wires & Breadboard/Stripboard**
  - Male-to-Female jumper wires for wiring GPIO header.

---

## Proximity Sensor
- [x] **VL53L1X Time-of-Flight (ToF) Laser Rangefinder Sensor**
  - Measures physical presence/distance up to ~4m/8m using eye-safe laser flight time over I2C.
  - Connects via I2C (VCC 3.3V Pin 1, GND Pin 9, SDA GPIO 2 Pin 3, SCL GPIO 3 Pin 5).
  - Fully integrated in `skull/proximity.py` and `skull/camera.py`.
- [ ] **4-pin Dupont Ribbon Cable (Female-to-Female, 20–30cm)**
  - Connects rangefinder module to Pi 5 GPIO header.

---

## Candle LEDs (Top of Skull)
- [x] **Self-Flickering LED Candle Bulbs**
  - Built-in hardware flicker effect (warm white / amber).

---

## Software / API Credentials
- [x] **Anthropic API Key** (Claude Haiku brain)
- [x] **OpenAI API Key** (Whisper speech-to-text)
- [x] **ElevenLabs Account** (Optional cloud TTS voice)
- [x] **Spotify Premium** (Optional Spotify voice control)

---

## Hardware Cost Summary (~$155–$160 USD)
| Component | Approx Cost |
|---|---|
| Raspberry Pi 5 (4GB) | ~$50 |
| Pi 5 Active Cooler | ~$5 |
| MicroSD 64GB | ~$12 |
| 27W Power Supply | ~$12 |
| UGREEN USB Sound Card | ~$10 |
| XMSJSIY Mini Speakers | ~$20 |
| Mic Capsule | ~$8 |
| Arducam IMX708 Camera | ~$30 |
| VL53L1X Laser Rangefinder | ~$10 |
| LEDs, Resistors, Wires | ~$10 |
| **Total** | **~$167 USD** |
