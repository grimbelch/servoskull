# Optic LED Wiring

Two addressable LEDs light the open optic tubes (Left Eye = index 0, Right Eye =
index 1); the third tube holds the camera. They are driven from GPIO 18 on the
Raspberry Pi 5 through a solder-pad "Smart LED" level shifter, and clocked out by
the Pi 5's RP1 PIO block in [core/eyes.py](core/eyes.py). What each colour means is
in the README ("Optic LEDs"); the rules live in [core/eye_states.py](core/eye_states.py)
and [core/eye_watch.py](core/eye_watch.py).

> [!IMPORTANT]
> The pixels fitted are **RGBW** (SK6812-type): four bytes per pixel, in **GRBW**
> order, not the three bytes of a WS2812B. Sent three bytes each, the first eye takes
> the second eye's leading byte as its white channel and the second eye shows the
> leftovers, which looks exactly like two LEDs with different colour orders.
> `EYE_LED_ORDER` sets the order (`GRBW` by default; `GRB` for plain WS2812B).

---

## Bill of materials

| Component | Notes |
|---|---|
| 2 × addressable RGBW pixels | 5 V, SK6812-type, GRBW byte order |
| "Smart LED" level shifter & inverter | Solder pads: `Clk`, `Data`, `Vin`, `GND` on the input side; `5vClk`, `5vData`, `Invert Data`, `GND` on the output side |
| 330 Ω resistor | In series on the shifted 5 V data line, never the 3.3 V side |
| 1000 µF electrolytic, ≥ 10 V | Across +5 V and GND **at the LED end**, stripe leg to GND |
| Heat-shrink | 2 mm for joints and the resistor |

---

## Why a level shifter

A WS2812-family pixel wants a logic high of at least 0.7 × V<sub>DD</sub> = 3.5 V. The
Pi's 3.3 V GPIO is below that and works only by luck, so the data line goes through
a buffer-type shifter built for an 800 kHz single-wire stream. (The BSS138
bi-directional modules sold for I²C cannot pass it cleanly.)

The shifter carries **data only**. Its `Vin` pad powers the board itself (a few mA);
it has no 5 V power pad on its output side, so the eyes take +5 V and ground straight
from the harness rails.

---

## Pad map

| From | To | Via | Wire |
|---|---|---|---|
| Pi pin 2 — 5 V | +5 V rail | direct | Red |
| Pi pin 6 — GND | GND rail | direct | Black |
| Pi pin 12 — GPIO 18 | `Data` | direct, no resistor | Green |
| +5 V rail | `Vin` | board logic only | Red |
| GND rail | `GND` (input side) | direct | Black |
| `5vData` | Eye 1 DIN | 330 Ω in series | White |
| Eye 1 DOUT | Eye 2 DIN | direct | White |
| +5 V rail (harness splice) | Eye 1 and Eye 2 +5 V | parallel — never from a shifter pad | Red |
| GND rail (harness splice) | Eye 1 and Eye 2 GND | parallel; the output-side `GND` pad also works | Black |
| 1000 µF across the rails | at the LED end | observe polarity | — |
| `Clk`, `5vClk`, `Invert Data` | no connection | `5vClk` is a shifted clock signal, not a 5 V supply | — |

Power and ground reach both eyes in **parallel**; data runs in **series**, from the
shifter through Eye 1 to Eye 2. Everything shares one common ground.

```text
 Pi pin 2  (5V)  ──┬──────────────► Vin              ┌──────────► Eye 1 +5V ── Eye 2 +5V
                   └─────────────────────────────────┘                     ┊
 Pi pin 12 (GPIO18) ──────────────► Data                                [1000 µF]
                                    5vData ──[330Ω]──► Eye 1 DIN           ┊
                                                       Eye 1 DOUT ──► Eye 2 DIN
 Pi pin 6  (GND) ──┬──────────────► GND              ┌──────────► Eye 1 GND ── Eye 2 GND
                   └─────────────────────────────────┘
```

---

## Assembly

1. **Rails.** Run a red +5 V line and a black ground line from the Pi header to the
   optic tubes, with splice points for the shifter, Eye 1 and Eye 2. Solder the
   1000 µF capacitor across them at the LED end, stripe to ground.
2. **Resistor.** Solder the white data wire to one leg and sleeve the joint and body.
   Trim the other leg to about 6 mm and solder it straight into `5vData`.
3. **Shifter.** `Vin` and input-side `GND` from the rails, `Data` from GPIO 18. Leave
   `Clk`, `5vClk` and `Invert Data` empty — the silkscreen truncates `5vClk` to
   "5vCl", which is easy to misread as a supply.
4. **Eyes.** Eye 1 in the left tube, Eye 2 in the right. +5 V and ground to each from
   the rails; data from the resistor to Eye 1 DIN, then Eye 1 DOUT to Eye 2 DIN. The
   arrows on each pixel point away from the Pi.
5. **Mount the board.** Use its mounting holes rather than burying it in the loom,
   and insulate the back so the pads cannot touch metal. Sleeve every bare splice.

---

## Software

The Pi 5's GPIO belongs to the RP1 southbridge, so `rpi_ws281x` (which drives the
Pi 4's PWM/DMA registers) cannot reach it. `core/eyes.py` packs the bytes itself and
sends them through Adafruit's `/dev/pio0` writer, which `requirements.txt` installs
on the Pi:

```bash
.venv/bin/pip install adafruit-blinka-raspberry-pi5-neopixel
```

> [!WARNING]
> Install that package **alone**. `adafruit-blinka` (and `adafruit-circuitpython-pixelbuf`,
> which needs it) pulls in `RPi.GPIO` and `rpi_ws281x`. `RPi.GPIO` overwrites the
> `rpi-lgpio` shim, after which the display fails with "Cannot determine SOC
> peripheral base address". If that happens:
> ```bash
> .venv/bin/pip uninstall -y adafruit-blinka adafruit-circuitpython-pixelbuf RPi.GPIO rpi_ws281x
> .venv/bin/pip install --force-reinstall --no-deps rpi-lgpio
> ```

`/dev/pio0` is `root:gpio`, mode 0660, so the service user needs to be in the `gpio`
group (`groups | grep gpio`); no root is required.

`.env`:

```bash
EYE_LED_PIN=18
EYE_LED_COUNT=2
EYE_LED_ORDER=GRBW
```

On start the service logs `[eyes] Initialized 2 GRBW eye LEDs on GPIO 18.` If it says
"mock mode" the writer is not installed.

---

## Bring-up

With the service stopped (`sudo systemctl stop omega7`), each primary in turn, then
the white channel:

```bash
cd ~/Servoskull && .venv/bin/python - <<'PY'
import time
from types import SimpleNamespace
from adafruit_raspberry_pi5_neopixel_write import neopixel_write
pin = SimpleNamespace(id=18)                      # the writer wants an object with .id
for name, grbw in (("red", (0, 255, 0, 0)), ("green", (255, 0, 0, 0)),
                   ("blue", (0, 0, 255, 0)), ("white", (0, 0, 0, 255))):
    neopixel_write(pin, bytes(grbw * 2)); print("both", name); time.sleep(2)
neopixel_write(pin, bytes(8))
PY
```

Both eyes should show the named colour each time.

| What you see | Where the fault is |
|---|---|
| Both dark | Writer not installed, wrong GPIO, the `Data` joint, or no power on `Vin`. A meter on `5vData` reads near 0 V at rest and a small steady voltage while the colours cycle. |
| Signal present, both dark | Downstream: the resistor joint, DIN/DOUT reversed, or the eyes' own +5 V and ground. |
| Eye 1 right, Eye 2 a different colour or dark, or Eye 1 turns white | Wrong byte count: the pixels are RGBW and are being sent three bytes each, or the reverse. Check `EYE_LED_ORDER`. |
| Eye 1 only | The DOUT-to-DIN hop between the eyes. |
| Flicker or sparkle | Common ground first, then the capacitor. |
| Left and right swapped | Swap the LEDs, not the code — index 0 is the left eye. |
