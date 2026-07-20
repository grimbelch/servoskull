import json
import os
import pathlib
import sys

from dotenv import load_dotenv

load_dotenv(override=True)

# ── Writable user-config layer ───────────────────────────────────────────────────
# Everything the OWNER personalizes (API keys, persona, voice, personalization) is
# user data that lives in a writable directory OUTSIDE the code tree, so the product
# image ships clean and the setup wizard has one place to read/write. Hardware
# defaults tuned to this physical build stay baked in as env/defaults below.
#
# Resolution order for any user-facing setting (see `_cfg`):
#   1. settings.json in USER_DATA_DIR   (written by the setup wizard)
#   2. environment / .env               (developer convenience)
#   3. hardcoded default                (last resort)
#
# USER_DATA_DIR defaults to the repo root — which is the systemd WorkingDirectory on
# the Pi and the run directory in dev, so existing memory/mood/history files are
# found unchanged. On the appliance image, set OMEGA7_DATA_DIR to a writable path
# such as /var/lib/omega7 or ~/.config/omega7.
_REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent
USER_DATA_DIR = pathlib.Path(os.getenv("OMEGA7_DATA_DIR", str(_REPO_ROOT))).expanduser()


def data_path(name: str) -> pathlib.Path:
    """Absolute path to a runtime/user-data file inside USER_DATA_DIR.

    All persisted state (memory, mood, quiet, reminders, history, owner profile,
    settings) resolves through here so the whole writable surface can be relocated
    with one env var and factory-reset in one place."""
    return USER_DATA_DIR / name


def _load_settings() -> dict:
    p = USER_DATA_DIR / "settings.json"
    try:
        if p.exists():
            data = json.loads(p.read_text())
            if isinstance(data, dict):
                return data
            print("[config] settings.json is not a JSON object; ignoring")
    except Exception as e:
        print(f"[config] settings.json unreadable ({e}); ignoring")
    return {}


_SETTINGS = _load_settings()


def _cfg(key: str, default: str = "") -> str:
    """Value for a user-facing setting: settings.json → env → default.

    Empty/absent values fall through so a blank field in the wizard doesn't shadow
    a valid env value during development."""
    v = _SETTINGS.get(key)
    if v is not None and str(v) != "":
        return str(v)
    return os.getenv(key, default)


# ── Secrets / API keys (user-provided via the setup wizard) ──────────────────────
# Optional at import so the app starts with only the backends it actually uses
# configured (e.g. local Piper voice needs no ElevenLabs key). Each consumer raises
# a clear error on first use if its key is missing.
ANTHROPIC_API_KEY = _cfg("ANTHROPIC_API_KEY", "")
OPENAI_API_KEY = _cfg("OPENAI_API_KEY", "")
ELEVENLABS_API_KEY = _cfg("ELEVENLABS_API_KEY", "")
ELEVENLABS_VOICE_ID = _cfg("ELEVENLABS_VOICE_ID", "")

# ── Bambu 3D Printer ─────────────────────────────────────────────────────────────
BAMBU_PRINTER_IP = _cfg("BAMBU_PRINTER_IP", "")
BAMBU_PRINTER_SERIAL = _cfg("BAMBU_PRINTER_SERIAL", "")
BAMBU_PRINTER_ACCESS_CODE = _cfg("BAMBU_PRINTER_ACCESS_CODE", "")

# Claude (Anthropic) powers the brain, idle utterances, memory extraction, and vision.
CLAUDE_MODEL = _cfg("CLAUDE_MODEL", "claude-haiku-4-5-20251001")

# ── Text-to-speech ───────────────────────────────────────────────────────────────
# "piper" (local, free) or "elevenlabs" (cloud, quota-limited)
TTS_BACKEND = _cfg("TTS_BACKEND", "elevenlabs")
PIPER_MODEL_PATH = _cfg("PIPER_MODEL_PATH", "models/servoskull.onnx")
# Wipe cached canned-phrase audio for one run after changing the ElevenLabs voice.
RESET_VOICE_CACHE = _cfg("RESET_VOICE_CACHE", "false").lower() == "true"

# ── Wake word (openWakeWord) ─────────────────────────────────────────────────────
# A built-in model name (e.g. "hey_jarvis") or a path to a custom .onnx model.
WAKE_WORD_MODEL = _cfg("WAKE_WORD_MODEL", "hey_jarvis")
WAKE_WORD_THRESHOLD = float(_cfg("WAKE_WORD_THRESHOLD", "0.5"))


def _resolve_input_device(raw: str) -> int:
    """Resolve a mic setting to a sounddevice input index.

    Accepts either a numeric index (e.g. "2", or "-1" for system default) or a
    case-insensitive name substring (e.g. "USB"). Resolving by name survives USB
    re-enumeration across rebuilds, where a fixed index silently points elsewhere.
    Returns -1 (system default) if a name can't be matched or audio isn't queryable.
    """
    raw = (raw or "").strip()
    if raw == "":
        return -1
    try:
        return int(raw)  # plain numeric index (incl. -1) — use verbatim
    except ValueError:
        pass
    try:
        import sounddevice as sd
        for idx, dev in enumerate(sd.query_devices()):
            if dev.get("max_input_channels", 0) > 0 and raw.lower() in dev["name"].lower():
                print(f"[config] MIC_DEVICE_INDEX '{raw}' matched device {idx}: {dev['name']!r}")
                return idx
        print(f"[config] WARNING: no input device name contains '{raw}'; using system default.")
    except Exception as e:
        print(f"[config] mic name resolution failed ({e}); using system default.")
    return -1


# ── Audio devices ────────────────────────────────────────────────────────────────
MIC_DEVICE_INDEX = _resolve_input_device(_cfg("MIC_DEVICE_INDEX", "-1"))
AUDIO_OUTPUT_DEVICE = int(_cfg("AUDIO_OUTPUT_DEVICE", "-1"))
# Pinned device for TTS/SFX — stays on the skull's own speaker even when BT is the PulseAudio default
VOICE_OUTPUT_DEVICE = int(_cfg("VOICE_OUTPUT_DEVICE", str(AUDIO_OUTPUT_DEVICE)))
# Set to true to print per-chunk RMS values during recording
AUDIO_DEBUG = os.getenv("AUDIO_DEBUG", "false").lower() == "true"

# ── Weather (get_weather tool; Open-Meteo, no key required) ──────────────────────
WEATHER_LAT = float(_cfg("WEATHER_LAT", "0.0"))
WEATHER_LON = float(_cfg("WEATHER_LON", "0.0"))

# ── Spotify (optional music control; Premium required) ───────────────────────────
SPOTIFY_CLIENT_ID = _cfg("SPOTIFY_CLIENT_ID", "")
SPOTIFY_CLIENT_SECRET = _cfg("SPOTIFY_CLIENT_SECRET", "")
SPOTIFY_REDIRECT_URI = _cfg("SPOTIFY_REDIRECT_URI", "http://127.0.0.1:8888/callback")
# Spotify Connect device name for local playback (Raspotify running on the Pi)
SPOTIFY_DEVICE_NAME = _cfg("SPOTIFY_DEVICE_NAME", "Omega-7")

# ── Google Home / Chromecast audio (optional) ────────────────────────────────────
GOOGLE_HOME_DEVICE = _cfg("GOOGLE_HOME_DEVICE", "")
# Casting is opt-in on macOS (emulator/dev) and opt-out on Linux/Pi, matching the
# original behavior before this setting was centralized.
CAST_ENABLED = _cfg("CAST_ENABLED", "false" if sys.platform == "darwin" else "true").lower() == "true"

# ── Camera / motion-triggered vision (optional) ──────────────────────────────────
CAMERA_ENABLED = _cfg("CAMERA_ENABLED", "false").lower() == "true"
CAMERA_DEVICE_INDEX = int(os.getenv("CAMERA_DEVICE_INDEX", "0"))
# ~8% of a 640x480 frame must change before we treat it as motion. The old
# default (5000 / ~1.6%) tripped on auto-exposure and sensor noise, firing a
# vision call every cooldown around the clock — a steady credit drain.
CAMERA_MOTION_THRESHOLD = int(os.getenv("CAMERA_MOTION_THRESHOLD", "25000"))
CAMERA_COOLDOWN = int(os.getenv("CAMERA_COOLDOWN", "120"))
# Hard ceiling on vision calls per rolling hour, independent of motion. A
# backstop so a misbehaving sensor can never run away with the API budget.
CAMERA_MAX_PER_HOUR = int(os.getenv("CAMERA_MAX_PER_HOUR", "15"))
# Mean grayscale brightness (0-255) below which a frame is considered blank/
# dark and is never sent to Claude. Guards against covered-lens / night frames.
CAMERA_MIN_BRIGHTNESS = int(os.getenv("CAMERA_MIN_BRIGHTNESS", "20"))

# ── Proximity trigger — VL53L1X time-of-flight sensor (I2C, optional) ─────────────
# When present, the camera fires vision on genuine physical approach instead of
# frame-difference motion — it doesn't false-trip on lighting/auto-exposure and it
# works in a dark room (a laser rangefinder needs no ambient light). If disabled or
# the sensor isn't found on the bus, camera.py transparently falls back to motion
# detection, so the Mac/Windows emulator is unaffected.
#
# Wiring (DWEII VL53L1X breakout → Pi 5 40-pin header, I2C1):
#   VIN → 3V3 (pin 1)   GND → GND (pin 6)   SDA → GPIO2 (pin 3)   SCL → GPIO3 (pin 5)
PROXIMITY_ENABLED = _cfg("PROXIMITY_ENABLED", "false").lower() == "true"
# Fire a vision call when a target is detected within this many centimetres.
PROXIMITY_THRESHOLD_CM = int(os.getenv("PROXIMITY_THRESHOLD_CM", "150"))
PROXIMITY_I2C_BUS = int(os.getenv("PROXIMITY_I2C_BUS", "1"))
# VL53L1X default I2C address. int(..., 0) accepts "0x29" or plain decimal.
PROXIMITY_I2C_ADDR = int(os.getenv("PROXIMITY_I2C_ADDR", "0x29"), 0)
# Ranging mode: 1=short (~1.3 m, most robust in bright light), 2=medium (~3 m),
# 3=long (~4 m). Long suits room-scale detection; drop to short if readings jitter.
PROXIMITY_RANGE_MODE = int(os.getenv("PROXIMITY_RANGE_MODE", "3"))
# Seconds between distance polls. 0.2 s (5 Hz) reacts promptly without busy-waiting.
PROXIMITY_POLL_INTERVAL = float(os.getenv("PROXIMITY_POLL_INTERVAL", "0.2"))
# GPIO BCM pin connected to XSHUT/SHDN to enable the sensor (defaults to GPIO 4, Pin 7)
PROXIMITY_XSHUT_PIN = int(os.getenv("PROXIMITY_XSHUT_PIN", "4"))


# ── Eye LEDs (Raspberry Pi GPIO, BCM numbering) — baked to this build ─────────────
LED_PIN_LEFT = int(os.getenv("LED_PIN_LEFT", "22"))
LED_PIN_CENTER = int(os.getenv("LED_PIN_CENTER", "23"))
LED_PIN_RIGHT = int(os.getenv("LED_PIN_RIGHT", "27"))

# ── Candle LEDs (self-flickering, GPIO-switched via transistor) — optional ────────
# The EDGELEC 2V flicker LEDs atop the skull flicker on their own internal IC; the
# GPIO only gates them on/off through a 2N2222 low-side switch, so the skull lights
# its candles when it wakes and snuffs them on shutdown. Disabled by default so the
# emulator and un-wired Pis are unaffected; set CANDLE_ENABLED=true in .env when
# wired. Current flows from the 5V rail through the transistor, not the GPIO, so the
# candle count is limited only by the rail — not the Pi's per-pin current budget.
CANDLE_ENABLED = _cfg("CANDLE_ENABLED", "false").lower() == "true"
CANDLE_PIN = int(os.getenv("CANDLE_PIN", "17"))

# ── Face display (GC9A01 1.28" round IPS, 240x240, 4-wire SPI) ───────────────────
# Optional "machine-spirit" eye/face display. Disabled by default so the Mac/Windows
# emulator and displayless Pis are unaffected; set DISPLAY_ENABLED=true in .env on the
# rig that has the panel wired.
#
# Audio is handled by a USB sound card (Ugreen), so the GPIO header is otherwise free
# except the eye LEDs (22/23/27) — SPI0 is fully available for the panel.
#
# Wiring (BCM):
#   VCC->3V3   GND->GND
#   SCL(SCK)->GPIO11   SDA(MOSI)->GPIO10   CS->GPIO8 (SPI0 CE0)
#   DC->GPIO25   RES->GPIO24   BLK->GPIO12 (or tie to 3V3 and set DISPLAY_BL_PIN=-1)
DISPLAY_ENABLED = os.getenv("DISPLAY_ENABLED", "false").lower() == "true"
DISPLAY_SPI_BUS = int(os.getenv("DISPLAY_SPI_BUS", "0"))       # spidev<bus>.<device>
DISPLAY_SPI_DEVICE = int(os.getenv("DISPLAY_SPI_DEVICE", "0")) # 0 -> CE0/GPIO8
DISPLAY_SPI_HZ = int(os.getenv("DISPLAY_SPI_HZ", "40000000"))  # 40 MHz; lower if flaky
DISPLAY_DC_PIN = int(os.getenv("DISPLAY_DC_PIN", "25"))
DISPLAY_RST_PIN = int(os.getenv("DISPLAY_RST_PIN", "24"))
DISPLAY_BL_PIN = int(os.getenv("DISPLAY_BL_PIN", "12"))        # -1 if BLK tied to 3V3
DISPLAY_ROTATION = int(os.getenv("DISPLAY_ROTATION", "0"))     # 0/90/180/270
DISPLAY_FINE_ROTATION = float(os.getenv("DISPLAY_FINE_ROTATION", "0.0"))  # software rotation offset (degrees, positive = clockwise)
DISPLAY_IDLE_TIMEOUT = float(os.getenv("DISPLAY_IDLE_TIMEOUT", "300.0"))  # seconds before showing idle animations (default: 5 minutes)


# ── Internal temperature monitoring (Raspberry Pi only) ──────────────────────────
# The skull watches its SoC temperature and speaks a warning when it climbs too high.
# The Pi 5 begins soft-throttling around 80°C and hard-throttles ~85°C, so the
# default warns at 80 and re-arms once it cools below 72. No-op on non-Pi hosts
# (no thermal sensor). Set TEMP_MONITOR_ENABLED=false to disable entirely.
TEMP_MONITOR_ENABLED = os.getenv("TEMP_MONITOR_ENABLED", "true").lower() == "true"
TEMP_WARN_THRESHOLD = float(os.getenv("TEMP_WARN_THRESHOLD", "80"))    # °C — warn at/above this
TEMP_CLEAR_THRESHOLD = float(os.getenv("TEMP_CLEAR_THRESHOLD", "72"))  # °C — re-arm once below this
TEMP_CHECK_INTERVAL = int(os.getenv("TEMP_CHECK_INTERVAL", "30"))      # seconds between readings
TEMP_WARN_COOLDOWN = int(os.getenv("TEMP_WARN_COOLDOWN", "300"))       # min seconds between repeat warnings

# ── Conversation history ─────────────────────────────────────────────────────────
# Stored inside USER_DATA_DIR. HISTORY_FILE may be a bare filename or an absolute path.
HISTORY_FILE = os.getenv("HISTORY_FILE", "history.json")

# How long to record after wake word (seconds)
RECORD_SECONDS = 10
# Silence threshold (RMS). Used both to stop recording early and to decide whether
# any speech occurred at all — capture quieter than this is discarded as silence.
# LOWER = more sensitive to quiet speech (but more prone to picking up background
# noise); raise it if it starts transcribing ambient hum. Recorder floor is ~300.
SILENCE_THRESHOLD = int(_cfg("SILENCE_THRESHOLD", "1000"))
SILENCE_DURATION = 1.5

# ── Persona (character = product data; owner profile = user data) ─────────────────
# The servo-skull character and all tool-usage instructions live in the shipped
# persona template; the owner's personal details come from owner.json (written by
# the setup wizard). See skull/persona.py.
from skull import persona as _persona  # noqa: E402  (needs USER_DATA_DIR above)

# The skull's own name — owner-settable at setup; defaults to the product name.
# Woven into the persona, spoken boot/barge-in lines, and the vision/STT prompts.
SKULL_NAME = _cfg("SKULL_NAME", "Omega-7")

_OWNER_PROFILE = _persona.load_owner(USER_DATA_DIR)
SYSTEM_PROMPT = _persona.build_system_prompt(_OWNER_PROFILE, SKULL_NAME)
# Owner location (e.g. "City, State") — drives localized idle news scopes.
OWNER_LOCATION = _persona.owner_location(_OWNER_PROFILE)


# ── Spoken Phrases ─────────────────────────────────────────────────────────────
WAKE_PHRASES = [
    "Yes, my Lord?",
    "How may this unit serve?",
    "Awaiting your command.",
    "Speak your will.",
    "This unit attends.",
    "Your command, my Lord?",
    "This unit is roused.",
    "At your service, my Lord.",
    "Vox-link open. Speak.",
    "The skull attends you.",
    "Command me.",
    "I hear you, my Lord.",
    "Systems attentive. Proceed.",
    "What is thy bidding?",
    "This unit stands ready.",
    "Ready to serve.",
    "You have my attention.",
    "Say the word, my Lord.",
    "The machine spirit stirs. Speak.",
    "Attending. State your need.",
    "Awakened and listening.",
    "I am summoned. What is required?",
    "Your servant awaits.",
    "Cogitators warm. Proceed.",
    "How may this unit assist?",
    "Speak, and it shall be done.",
    "This unit answers your call.",
    "Online and attentive.",
    "The Omnissiah's servant listens.",
    "Yes? This unit stands by.",
    "I attend your word.",
    "Awaiting instruction, my Lord.",
    "Roused from vigil. Command me.",
    "What service do you require?",
    "The skull turns to you.",
    "Speak your need, my Lord.",
    "This unit is at your command.",
    "Listening. Proceed when ready.",
    "Your will, my Lord?",
    "Auspex fixed upon you. Speak.",
    "Ready and awaiting your word.",
    "The vox awaits your voice.",
    "This unit heeds you.",
    "Standing ready, my Lord.",
    "Command received channel open.",
    "I am here. Speak.",
]

COGITATION_PHRASES = [
    "Cogitating.",
    "Consulting the archives.",
    "Accessing the data-vaults.",
    "The machine spirits deliberate.",
    "Searching the cogitator.",
    "Processing.",
    "Parsing the datastreams.",
    "Querying the noosphere.",
    "Consulting the sacred protocols.",
    "Cross-referencing the lexicanum.",
    "The logic-engines turn.",
    "Sifting the memory-coils.",
    "Invoking the calculus of the Omnissiah.",
    "Communing with the machine spirit.",
    "Retrieving from deep storage.",
    "Decrypting the archive-runes.",
    "The cogitator banks whir.",
    "Aligning the data-matrices.",
    "Interrogating the datacore.",
    "Threading the logic-circuits.",
    "Consulting the Standard Template Construct.",
    "Sanctifying the calculation.",
    "The valves warm to their task.",
    "Scanning the sacred registries.",
    "Compiling the response.",
    "Weighing the variables.",
    "The data-djinn stir.",
    "Traversing the memory-stacks.",
    "Reconciling the archive fragments.",
    "The binary cant flows.",
    "Enumerating the possibilities.",
    "Consulting the codified wisdom.",
    "The thought-engines labour.",
    "Filtering the vox-static.",
    "Unspooling the data-scrolls.",
    "Correlating the auspex returns.",
    "The relays click and settle.",
    "Distilling the archive-truth.",
    "Summoning the relevant lore.",
    "The cogitation deepens.",
    "Rousing the dormant subroutines.",
    "Tracing the query through the datavaults.",
    "The machine spirit ponders.",
    "Assembling the verdict.",
    "Consulting the Rites of Recall.",
    "Marshalling the archive-daemons.",
]

SEARCH_PHRASES = [
    "One moment. This unit consults the archives.",
    "Accessing the data-vaults. Stand by.",
    "Querying the noosphere. A moment, my Lord.",
    "Searching the cogitator banks.",
    "Reaching into the datastreams. Stand by.",
    "This unit interrogates the archives. A moment.",
    "Consulting distant data-shrines. Hold.",
    "Casting the query wide. One moment, my Lord.",
    "Auspex sweeping the noosphere. Stand by.",
    "Retrieving the record. A moment.",
    "Delving the deep archives. Hold, my Lord.",
    "Opening a channel to the data-vaults. Stand by.",
    "This unit seeks the answer. One moment.",
    "Trawling the memory-coils. A moment, my Lord.",
    "Dispatching the query-daemons. Stand by.",
    "Consulting the lexicanum. Hold a moment.",
    "Scanning the sacred registries. Stand by.",
    "The cogitators reach outward. One moment.",
    "Summoning the record from deep storage. Hold.",
    "This unit queries the wider web. A moment, my Lord.",
    "Threading the datastreams. Stand by.",
    "Seeking through the archive-strata. One moment.",
    "Reaching across the vox-net. Hold, my Lord.",
    "The query is dispatched. Stand by.",
    "Cross-referencing the data-shrines. A moment.",
    "Sifting the far archives. One moment, my Lord.",
    "Engaging the search-rites. Stand by.",
    "This unit consults the wider record. Hold.",
    "Combing the noosphere for your answer. A moment.",
    "Data-daemons are dispatched. Stand by, my Lord.",
    "Opening the sacred conduits. One moment.",
    "Requesting the record. Hold a moment.",
    "The auspex ranges far. Stand by.",
    "Interrogating distant cogitators. A moment, my Lord.",
    "Casting into the datavaults. Hold.",
    "This unit gathers the intelligence. One moment.",
    "Querying the archive-network. Stand by.",
    "Retrieving from the wider web. A moment, my Lord.",
    "Consulting the outer data-shrines. Hold.",
    "Search-rites underway. Stand by.",
    "Reaching for the answer. One moment, my Lord.",
    "The vox carries your query outward. Hold.",
    "Delving for the record. Stand by.",
    "Fetching the data. One moment, my Lord.",
]

ACK_PHRASES = [
    "Acknowledged.",
    "As you command. One moment.",
    "Understood. Processing.",
    "Compliance. Stand by.",
    "By your will, my Lord.",
    "Affirmative. This unit attends to it.",
    "It shall be done.",
    "As you will, my Lord.",
    "Command received.",
    "Understood. One moment.",
    "Compliance.",
    "This unit obeys.",
    "At once, my Lord.",
    "Very well. Processing.",
    "Your word is heard.",
    "Acknowledged. Working.",
    "So ordered.",
    "Attending to it now.",
    "By the Omnissiah, it shall be so.",
    "Received and understood.",
    "As directed. Stand by.",
    "This unit complies.",
    "Noted. One moment, my Lord.",
    "Affirmative.",
    "Your command is registered.",
    "Understood, my Lord. Working.",
    "It is being done.",
    "Instruction accepted.",
    "Consider it done.",
    "At your word. Processing.",
    "This unit sets to the task.",
    "Very good, my Lord.",
    "Order confirmed.",
    "As you say. One moment.",
    "The task is begun.",
    "Heard and obeyed.",
    "Processing your command.",
    "Right away, my Lord.",
    "Understood. Attending.",
    "By your command.",
    "Acknowledged, my Lord.",
    "This unit takes it in hand.",
    "So it shall be.",
    "Compliance. Working now.",
    "Your bidding is done.",
    "Understood. This unit proceeds.",
]

SILENCE_PHRASES = [
    "This unit awaits your command.",
    f"Silence. {SKULL_NAME} stands ready when you are.",
    "I am listening, my Lord. Speak when you will.",
    "The vox is open. State your need.",
    "Nothing? This unit holds its vigil, awaiting your word.",
    "No words reach this unit. I await you still.",
    "Only silence. Speak when you are ready, my Lord.",
    "The vox carries nothing. This unit waits.",
    "I hear only quiet. State your need when you will.",
    "Silence on the vox. This unit keeps its watch.",
    "Nothing spoken. I remain attentive, my Lord.",
    "The channel is open, yet empty. I await your voice.",
    "This unit detects no command. Speak when ready.",
    "Awaiting your word still, my Lord.",
    "No speech received. This unit holds ready.",
    "Quiet reigns. I stand by for your command.",
    f"{SKULL_NAME} waits. Speak when you are ready.",
    "The auspex hears nothing. I remain at your service.",
    "You summoned this unit, yet said nothing. I wait.",
    "Silence noted. This unit stands ready.",
    "No instruction given. I hold my vigil, my Lord.",
    "The vox is clear but silent. Speak your need.",
    "This unit listens still. Command me when ready.",
    "Nothing heard. I await your word, my Lord.",
    "Only stillness. This unit remains attentive.",
    "No voice on the channel. I stand ready.",
    "This unit waits in silence for your command.",
    "You have my attention, though no word has come.",
    "Empty vox. Speak when it pleases you, my Lord.",
    "I detect no speech. This unit holds its post.",
    "Silence answers. Yet this unit remains ready.",
    "Awaiting speech. The channel stays open, my Lord.",
    "No command discerned. I keep the vox open.",
    "This unit hears no order. I stand by.",
    "Quiet still. Speak your will when ready, my Lord.",
    "The moment passes in silence. I await you.",
    "Nothing yet. This unit remains at the ready.",
    "No words. This unit maintains its vigil.",
    "The vox waits, empty. Speak when you will.",
    "Silence, my Lord. I remain wholly at your service.",
    "This unit stands attentive, though none has spoken.",
    "I await your voice. The channel remains open.",
    "No utterance received. This unit holds ready.",
    "Still listening, my Lord. Speak when the moment comes.",
    "The vigil continues. Command me when you are ready.",
]


# ── Display and Animation Settings ──────────────────────────────────────────
DISPLAY_FPS = 30.0
DISPLAY_MOOD_COLORS = {
    "neutral": (0, 100, 255),
    "thinking": (200, 50, 255),
    "speaking": (0, 200, 255),
    "angry": (255, 0, 0),
    "sad": (0, 50, 100),
    "happy": (0, 255, 50),
    "alarm": (255, 0, 0),
}

# ── Eyes PWM Tunings ─────────────────────────────────────────────────────────
EYES_PWM_FREQ = 1000
EYES_IDLE_MIN = 3.0
EYES_IDLE_MAX = 100.0

# ── Thermal Sensor Path ──────────────────────────────────────────────────────
THERMAL_SENSOR_PATH = "/sys/class/thermal/thermal_zone0/temp"
