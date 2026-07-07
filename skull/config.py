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

# Claude (Anthropic) powers the brain, idle utterances, memory extraction, and vision.
CLAUDE_MODEL = _cfg("CLAUDE_MODEL", "claude-haiku-4-5-20251001")

# ── Text-to-speech ───────────────────────────────────────────────────────────────
# "piper" (local, free) or "elevenlabs" (cloud, quota-limited)
TTS_BACKEND = _cfg("TTS_BACKEND", "piper")
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

# ── Eye LEDs (Raspberry Pi GPIO, BCM numbering) — baked to this build ─────────────
LED_PIN_LEFT = int(os.getenv("LED_PIN_LEFT", "22"))
LED_PIN_CENTER = int(os.getenv("LED_PIN_CENTER", "23"))
LED_PIN_RIGHT = int(os.getenv("LED_PIN_RIGHT", "27"))

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
# Silence threshold to stop recording early (RMS)
SILENCE_THRESHOLD = 1000
SILENCE_DURATION = 1

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
