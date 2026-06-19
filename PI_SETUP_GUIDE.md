# Omega-7 Servo Skull — Raspberry Pi 5 Setup Guide

A start-to-finish guide for building the skull from a fresh Raspberry Pi 5, matched
to this project's actual code (pin assignments come straight from [skull/config.py](skull/config.py)).

> **Golden rule:** Do **all wiring with the Pi powered off and unplugged.** Only the
> camera ribbon and GPIO header are static-sensitive — handle the board by its edges.

---

## 0. Inventory check — what should be in front of you

From [SHOPPING_LIST.txt](SHOPPING_LIST.txt), you should have:

| Group | Item |
|---|---|
| Core | Raspberry Pi 5, official Active Cooler, 64 GB microSD, 27 W USB-C PD supply |
| Audio | UGREEN USB sound card, XMSJSIY mini speakers, 3.5 mm electret/lavalier mic |
| Vision | Arducam IMX708 Wide camera + the included 15-to-22-pin CSI adapter cable |
| Eyes | 3× 5 mm red LEDs, 3× 220 Ω resistors, M-F jumper wires, mini breadboard/perfboard |
| Display | GC9A01 1.28" round IPS panel (240×240, SPI) + 7 jumper wires |
| Setup-only | micro-HDMI→HDMI cable, USB keyboard (borrow if needed) |
| Optional | HC-SR04 ultrasonic sensor (not yet wired in software — skip for now) |

If anything core is missing, stop and source it before Friday — the Pi 5 **requires** the
27 W supply (under-powering causes random crashes) and **will throttle** without the cooler.

---

## 1. Install the Active Cooler (do this first, board unpowered)

1. Peel the film off the cooler's thermal pads.
2. Align the fan/heatsink over the Pi 5 SoC; the two spring-pins push into the holes
   either side of the SoC (they click).
3. Plug the fan's 4-pin cable into the small **FAN** connector near the USB ports.
4. Orient the skull mount so the fan exhaust points **away** from where the mic will sit —
   fan noise into the mic ruins wake-word detection.

---

## 2. Flash the microSD (on your Mac, before touching the Pi)

1. Download **Raspberry Pi Imager** from raspberrypi.com/software.
2. Insert the microSD.
3. In Imager:
   - **Device:** Raspberry Pi 5
   - **OS:** Raspberry Pi OS (64-bit) — the full desktop version
   - **Storage:** your microSD

> **OS version note:** current Imager installs **Debian _Trixie_** (Python 3.13, PipeWire
> audio), which is what this guide targets. Trixie dropped some packages this build used to
> rely on — `pi_setup.sh` already handles the substitutions (`libopenblas-dev` for the old
> `libatlas-base-dev`; openWakeWord installed ONNX-only because `tflite-runtime` has no
> Python-3.13 wheels). Audio also goes through **PipeWire**, not PulseAudio (see §6).
4. Click the gear / **Edit Settings** before writing and pre-configure:
   - **Hostname:** `omega7`
   - **Username/password:** pick a user (e.g. `sean`) — the systemd service runs as this user
   - **Wi-Fi:** your SSID + password + country
   - **Locale/timezone**
   - **Enable SSH** (password or your key) — lets you work headless later
5. Write and verify. This takes a few minutes.

> 64-bit OS matters: `picamera2`, the ONNX voice model, and the Python wheels all assume it.

---

## 3. First boot & base OS config

1. Insert the microSD, connect micro-HDMI + keyboard (or go straight to SSH if Wi-Fi worked).
2. Plug in the 27 W supply **last**. The Pi boots.
3. From your Mac you should be able to: `ssh sean@omega7.local`
4. Update everything and enable the SPI bus the round display needs:

```bash
sudo apt-get update && sudo apt-get full-upgrade -y
sudo raspi-config nonint do_spi 0      # enable SPI0 (the pi_setup.sh script also does this)
sudo reboot
```

The camera (CSI) and USB audio need **no** manual enabling — they auto-detect.

---

## 4. Wiring

### Powered off. Unplug the USB-C supply before you touch a single pin.

### 4.1 GPIO header reference (Pi 5 — same 40-pin layout as Pi 4)

Only the pins this build uses are annotated. Physical pin 1 is the corner nearest the
microSD/Wi-Fi end, with the SD card facing you and USB ports to the right.

```
            3V3  (1) (2)  5V
    [I2C] GPIO2  (3) (4)  5V
          GPIO3  (5) (6)  GND
          GPIO4  (7) (8)  GPIO14
            GND  (9) (10) GPIO15
         GPIO17 (11) (12) GPIO18
  LED→ ●  GPIO27(13) (14) GND  ● ←LED cathodes common GND
  LED→ ●  GPIO22(15) (16) GPIO23  ● ←LED
DISP VCC● 3V3  (17) (18) GPIO24 ● ←DISP RES
DISP SDA● GPIO10(19) (20) GND   ● ←DISP GND
         GPIO9 (21) (22) GPIO25 ● ←DISP DC
DISP SCL● GPIO11(23) (24) GPIO8  ● ←DISP CS (CE0)
            GND(25) (26) GPIO7
         ID_SD (27) (28) ID_SC
          GPIO5(29) (30) GND
          GPIO6(31) (32) GPIO12 ● ←DISP BLK (backlight)
         GPIO13(33) (34) GND
         GPIO19(35) (36) GPIO16
         GPIO26(37) (38) GPIO20
            GND(39) (40) GPIO21
```

There are **no pin conflicts** between the LEDs and the display — the LEDs use plain GPIO
(13/15/16) and the display uses the SPI0 bus (19/23/24) plus three control pins (18/22/32).

### 4.2 Eye LEDs (3× red, GPIO PWM) — `eyes.py`

Each LED: **GPIO pin → 220 Ω resistor → LED long leg (anode +) → LED short leg (cathode −) → GND.**
The resistors in the EDGELEC pack are sized for 6–12 V — **don't use them.** Use your separate
220 Ω resistors (≈7 mA per LED at 3.3 V, well within the Pi's per-pin limit).

| LED | GPIO (BCM) | Physical pin | Config var |
|---|---|---|---|
| Left | GPIO22 | 15 | `LED_PIN_LEFT` |
| Center | GPIO23 | 16 | `LED_PIN_CENTER` |
| Right | GPIO27 | 13 | `LED_PIN_RIGHT` |

```
 GPIO22 (pin15) ──[220Ω]──▶|── ┐
 GPIO23 (pin16) ──[220Ω]──▶|── ┤  (▶| = LED, flat/short leg = cathode)
 GPIO27 (pin13) ──[220Ω]──▶|── ┤
                               └──── common ──► GND (pin 14)
```

Build this on the mini breadboard/perfboard. Tie all three cathodes to one GND rail, run a
single wire from that rail to **pin 14 (GND)**. "Center" can drive a third LED or be left for a
future eye — wire all three now to match the code.

### 4.3 Round face display — GC9A01 1.28" (4-wire SPI) — `display.py`

Wiring is exactly as documented in [skull/config.py](skull/config.py) (lines 25–28):

| Panel pin | Connects to | GPIO (BCM) | Physical pin |
|---|---|---|---|
| GND | Ground | — | 20 |
| VCC | 3.3 V | — | 17 |
| SCL (SCK) | SPI clock | GPIO11 | 23 |
| SDA (MOSI) | SPI data | GPIO10 | 19 |
| RES | Reset | GPIO24 | 18 |
| DC | Data/command | GPIO25 | 22 |
| CS | SPI chip-select (CE0) | GPIO8 | 24 |
| BLK | Backlight | GPIO12 | 32 |

> **VCC goes to 3.3 V, not 5 V.** The GC9A01's logic is 3.3 V; 5 V can damage it.
> If your panel's backlight is always-on you may instead tie BLK → 3.3 V and set
> `DISPLAY_BL_PIN=-1` in `.env`, freeing pin 32.

```
 GC9A01            Raspberry Pi 5 header
 ───────           ─────────────────────
  VCC  ───────────► 3V3   (pin 17)
  GND  ───────────► GND   (pin 20)
  SCL  ───────────► GPIO11 SCLK (pin 23)
  SDA  ───────────► GPIO10 MOSI (pin 19)
  CS   ───────────► GPIO8  CE0  (pin 24)
  DC   ───────────► GPIO25      (pin 22)
  RES  ───────────► GPIO24      (pin 18)
  BLK  ───────────► GPIO12      (pin 32)
```

### 4.4 Camera — Arducam IMX708 (CSI ribbon)

The Pi 5 has **two narrow 22-pin** camera/display connectors (labelled CAM/DISP 0 and 1).
The Arducam kit includes the 15-to-22-pin adapter you need.

1. Pi **off and unplugged.**
2. Lift the black tab on connector **CAM/DISP 1** (the one nearer the USB-C/HDMI edge).
3. Insert the ribbon **blue stripe facing the USB/Ethernet side** of the board (contacts
   face the opposite way). Push the tab down to lock.
4. Do the camera-end of the ribbon the same way (contacts to the lens side).
5. Never insert/remove the ribbon while powered.

`picamera2` auto-detects the IMX708 — your [skull/camera.py](skull/camera.py) uses
it directly. You'll flip `CAMERA_ENABLED=true` in step 6.

### 4.5 Audio — UGREEN USB sound card

No GPIO involved — all USB/3.5 mm:

```
 [Pi USB port] ── UGREEN USB sound card ──┬── 3.5mm OUT ──► speaker 3.5mm IN
                                          └── 3.5mm IN  ──► electret/lavalier mic
 [Pi USB port] ── XMSJSIY speaker USB (power)
```

- UGREEN card → any Pi USB port (use a **USB-A 2.0** port — the black ones — to keep the
  blue USB 3.0 ports free and avoid 2.4 GHz Wi-Fi interference).
- Mic plug → UGREEN **mic in**.
- Speaker audio cable → UGREEN **headphone out**; speaker USB → Pi for power.
- You'll capture the device indices in step 6.

### 4.6 (Optional) HC-SR04 proximity sensor — skip for now

Not referenced anywhere in the current code, so leave it out of v1. When you add software
support later: VCC→5 V, GND→GND, Trig→a spare GPIO, and Echo **through a 1 kΩ + 2 kΩ divider**
(the Echo line is 5 V and will damage a 3.3 V GPIO without it).

### Wiring sanity check before powering on

- [ ] Display **VCC on pin 17 (3.3 V)** — not a 5 V pin.
- [ ] LED resistors are your **220 Ω** ones, not the pack resistors.
- [ ] LED long legs toward the resistor/GPIO, short legs to GND.
- [ ] Nothing bridging two header pins (look for stray strands).
- [ ] Camera ribbon fully seated, tab locked, correct orientation.

---

## 5. Deploy the software

The project expects to live at `~/skull`. From an SSH session on the Pi:

```bash
# Option A — clone from your git remote (preferred):
git clone <your-repo-url> ~/skull

# Option B — copy from your Mac over the network:
#   (run this ON YOUR MAC, from the project folder)
#   rsync -av --exclude '.venv' --exclude '.git' "./" sean@omega7.local:~/skull/
```

Then copy your secrets file in (it is git-ignored, so it won't have come from the clone):

```bash
# From your Mac:
scp "/Users/sean/Desktop/Skull Project/.env" sean@omega7.local:~/skull/.env
```

Run the one-shot installer — it installs system packages, builds the venv, fetches the
Piper voice + wake-word models, and installs both the `omega7` and `raspotify` services:

```bash
cd ~/skull
bash pi_setup.sh
```

At the end it prints your **audio device indices** — keep that output, you need it next.

> **Pi 5 GPIO shim (important).** The classic `RPi.GPIO` library does **not** work on the Pi 5
> (its GPIO chip changed). Both [skull/eyes.py](skull/eyes.py) and [skull/display.py](skull/display.py)
> import `RPi.GPIO`, and without it the eyes/display silently do nothing (`display.py` prints
> "spidev/RPi.GPIO/Pillow unavailable — skipping"). Install the drop-in shim into the venv:
> ```bash
> # rpi-lgpio depends on lgpio, which has NO prebuilt wheel for Python 3.13 — it compiles
> # from source, so install the build tools first or the wheel build fails (swig / -llgpio):
> sudo apt install -y swig liblgpio-dev python3-dev
> cd ~/skull && source .venv/bin/activate
> pip uninstall -y RPi.GPIO          # remove the incompatible classic lib if present
> pip install rpi-lgpio              # provides the RPi.GPIO API on Pi 5
> ```
> (If you ever see "RuntimeError: Cannot determine SOC peripheral base address", that's the
> missing shim. `error: command 'swig' failed` or `cannot find -llgpio` means the build deps
> above aren't installed.)

---

## 6. Configure `.env`

Edit `~/skull/.env` and set the hardware-specific values. The keys come from
[skull/config.py](skull/config.py):

```ini
# Audio — route through PipeWire, NOT the raw USB card. On Trixie the audio server
# (PipeWire) owns the card; opening it raw via PortAudio gives "Device unavailable"
# (PaErrorCode -9985) or paInvalidSampleRate, and mixing raw capture with PipeWire
# playback caused PortAudio double-free crashes. -1 = PortAudio's default device,
# which is PipeWire — it resamples and shares the card cleanly.
MIC_DEVICE_INDEX=-1
AUDIO_OUTPUT_DEVICE=-1

# Cast OFF — pychromecast isn't installed on the Pi. With it on, the reply audio is
# routed to a (missing) Google Home and silently dropped instead of playing locally.
CAST_ENABLED=false

# Round face display — turn it on now that it's wired
DISPLAY_ENABLED=true
# If you tied BLK to 3.3V instead of pin 32, also set: DISPLAY_BL_PIN=-1

# Camera vision — turn it on now that the ribbon is connected
CAMERA_ENABLED=true
```

> **Why `-1` instead of the UGREEN's index?** Pinning the raw card (e.g. `hw:2,0`) fights the
> PipeWire session for exclusive access and skips resampling. Letting PipeWire mediate is what
> makes voice **and** Spotify share the one speaker. Only pin a specific index if you've
> deliberately disabled PipeWire.

Inspect devices any time (sounddevice's list shows which is the PipeWire `default`):

```bash
cd ~/skull && source .venv/bin/activate
python -c "import sounddevice as sd; print(sd.query_devices())"
```

Set the **PipeWire** default sink to the UGREEN output once (so music routes correctly). Trixie
uses `wpctl`, not `pactl`:

```bash
wpctl status                           # find the USB sink's numeric ID under "Sinks"
wpctl set-default <id>                 # e.g. wpctl set-default 45
```
(If you prefer the `pactl` syntax, `sudo apt install pulseaudio-utils` adds a PipeWire-compatible shim.)

---

## 7. Bring-up tests (one subsystem at a time)

Run each from `cd ~/skull && source .venv/bin/activate`. Test before final assembly so you
can still reach the wiring.

**Eye LEDs:**
```bash
python -c "from skull import eyes, config, time; eyes.setup(config.LED_PIN_LEFT, config.LED_PIN_CENTER, config.LED_PIN_RIGHT); eyes.on(); __import__('time').sleep(2); eyes.off(); eyes.cleanup()"
```
All three LEDs should glow for 2 s. If one stays dark, check its LED polarity and resistor.

**Round display:**
```bash
python -c "from skull import display; display.setup(); display.on(); __import__('time').sleep(3); display.cleanup()"
```
You should see the glowing red iris with the Mechanicus tick-ring. Nothing? Re-check VCC=3.3 V,
that SPI is enabled (`ls /dev/spidev0.*`), and the DC/RES/CS pins.

**Camera:**
```bash
libcamera-hello -t 3000     # 3-second preview; confirms the IMX708 is detected
```

**Mic + speaker:** use the existing helper —
```bash
python _miccheck.py         # see _miccheck.py
```
Speak and confirm it registers input; play any test sound to confirm output.

---

## 8. Run it

Manual run (watch the logs live while you shake out problems):
```bash
cd ~/skull && source .venv/bin/activate && python -m skull.main
```

As the auto-start service (already enabled by `pi_setup.sh`):
```bash
sudo systemctl start omega7
journalctl -u omega7 -f          # follow logs
sudo systemctl status omega7
```

The service ([omega7.service](omega7.service)) restarts on failure and launches on every boot,
so the finished skull is a headless appliance — power it and it wakes on its own.

Say the wake word and Omega-7 should answer in character, eyes and iris pulsing with its
speech. `WAKE_WORD_MODEL` in `.env` selects the openWakeWord model — a built-in name like
`hey_jarvis`, or a path to a custom ONNX model (this build uses
`models/Hey_Robot_20260401_210600.onnx`, i.e. "Hey Robot").

---

## 9. Troubleshooting

| Symptom | Likely cause / fix |
|---|---|
| Random reboots / lightning-bolt icon | Under-powered — use the 27 W supply, not a phone charger |
| Display stays black (backlight on) | VCC not on 3.3 V; SPI not enabled (`do_spi 0` + reboot); DC/RES miswired or floating; SPI clock too fast — set `DISPLAY_SPI_HZ=8000000` in `.env` |
| `display.py` prints "spidev/RPi.GPIO/Pillow unavailable — skipping" | Pi 5 GPIO shim missing — install `rpi-lgpio` (+ `swig liblgpio-dev`, see §5); or `pip install spidev Pillow` |
| One LED dark | Reversed polarity (flip the LED) or open resistor joint |
| Camera "not detected" | Ribbon orientation/seating; only insert with power off; try `libcamera-hello` |
| Boot sound, then `-9985` / `paInvalidSampleRate` in logs | Audio pinned to the raw USB card — set `MIC_DEVICE_INDEX=-1` and `AUDIO_OUTPUT_DEVICE=-1` (route via PipeWire, §6) |
| Speaks the acknowledgement then goes silent; `[cast] Discovery error: No module named 'pychromecast'` | Cast enabled without the library — set `CAST_ENABLED=false` (§6) |
| `double free` / `Segmentation fault` / `Pa_CloseStream` abort | Old code — ensure the Pi has pulled the latest (single-stream recorder + reused wake-word model) |
| No mic input / wrong device | Recording captures silence — confirm `MIC_DEVICE_INDEX=-1`; test with `python -c "import sounddevice as sd,numpy as np; d=sd.rec(int(3*44100),samplerate=44100,channels=1,dtype='int16',blocking=True); sd.wait(); print('RMS',float(np.sqrt(np.mean(d.astype('f4')**2))))"` |
| Music plays but voice doesn't (or vice-versa) | PipeWire default sink not the UGREEN — `wpctl set-default <id>` (§6) |
| Vision burns API credits | Tune `CAMERA_COOLDOWN`, `CAMERA_MOTION_THRESHOLD`, `CAMERA_MAX_PER_HOUR` in `.env` |

---

## 10. Final assembly notes

- Mount the camera in the eye socket, the round display where the "machine-spirit eye" shows,
  the LEDs behind the red lenses, the mic in the nasal cavity, fan exhaust **away** from the mic.
- Hot-glue the breadboard/perfboard so jumper wires can't pull loose with the skull's movement.
- Leave a service loop of slack in the camera ribbon — it's the most fragile cable.
- The self-flickering candle LEDs are independent (their own power, no Pi control) — wire them
  straight to their supply.
- Once everything tests good, let the `omega7` service handle startup; you shouldn't need a
  keyboard/HDMI again.

The Omnissiah smiles upon a clean install. Praise the Machine God.
```
