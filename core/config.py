import json
import os
import pathlib
import re
import sys

import stat
import tempfile
import threading
from dotenv import load_dotenv

# override=False so a real environment variable beats the file, which is the
# convention everywhere else and the only way to override a setting per-run:
# `AUDIO_DEBUG=true python -m core.main`, or a systemd drop-in on the appliance.
# With override=True the file silently won, so a drop-in for any key named in
# .env did nothing at all and left no trace of why.
#
# Nothing is lost by this: keys absent from the environment are still loaded from
# the file exactly as before. On the Pi, systemd already reads the same file via
# EnvironmentFile=, so the values reach the process either way.
load_dotenv(override=False)

# ── Writable user-config layer ───────────────────────────────────────────────────
# Everything the OWNER personalizes (API keys, persona, voice, personalization) is
# user data that lives in a writable directory OUTSIDE the code tree, so the product
# image ships clean and the setup wizard has one place to read/write. Hardware
# defaults tuned to this physical build stay baked in as env/defaults below.
#
# Resolution order for any user-facing setting (see `_cfg`):
#   1. settings.json in USER_DATA_DIR   (written by the setup wizard)
#   2. environment variable             (per-run override, systemd drop-in)
#   3. .env file                        (developer convenience, persistent)
#   4. hardcoded default                (last resort)
#
# USER_DATA_DIR defaults to ~/.config/omega7. On an appliance image, set
# OMEGA7_DATA_DIR to another writable path such as /var/lib/omega7.
_REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent
USER_DATA_DIR = pathlib.Path(os.getenv("OMEGA7_DATA_DIR", "~/.config/omega7")).expanduser()
USER_DATA_DIR.mkdir(parents=True, exist_ok=True)

def atomic_write(path, data, mode: int | None = None) -> None:
    """Write a file so that a power cut leaves either the old or the new contents,
    never a truncated file: write a temp file beside it, fsync, rename over the
    target, then fsync the directory. `mode` defaults to the existing file's mode
    (or 0o644 for a new file); the temp file gets it before it is renamed in, so
    secrets are never briefly world-readable."""
    path = pathlib.Path(path)
    payload = data.encode("utf-8") if isinstance(data, str) else data
    if mode is None:
        mode = stat.S_IMODE(path.stat().st_mode) if path.exists() else 0o644
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.tmp")
    try:
        os.fchmod(fd, mode)
        with os.fdopen(fd, "wb") as f:
            f.write(payload)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise
    try:
        dir_fd = os.open(path.parent, os.O_RDONLY)
        try:
            os.fsync(dir_fd)
        finally:
            os.close(dir_fd)
    except OSError:
        pass


_env_lock = threading.Lock()


def env_file() -> pathlib.Path:
    """The .env the service loads: the repo copy if present, else the user-data one."""
    repo_env = pathlib.Path(__file__).resolve().parent.parent / ".env"
    return repo_env if repo_env.exists() else pathlib.Path("~/.config/omega7/.env").expanduser()


def set_env_vars(values: dict, drop_prefixes: tuple = (), create: bool = True) -> None:
    """Set KEY=value lines in .env (replacing any existing ones for those keys and
    any line starting with a prefix in `drop_prefixes`), atomically and under the
    env lock so concurrent updates can't lose each other's changes."""
    env_path = env_file()
    with _env_lock:
        if not env_path.exists() and not create:
            return
        content = env_path.read_text(encoding="utf-8") if env_path.exists() else ""
        drop = tuple(f"{k}=" for k in values) + tuple(drop_prefixes)
        lines = [l for l in content.splitlines() if not l.startswith(drop)]
        lines += [f"{k}={v}" for k, v in values.items()]
        atomic_write(env_path, "\n".join(lines) + "\n", mode=None if env_path.exists() else 0o600)


def _update_env_var(key: str, value: str) -> None:
    """Thread-safe, atomic update of a variable in the .env file."""
    try:
        set_env_vars({key: value}, create=False)
    except Exception as e:
        print(f"[config] Failed to update .env with {key}: {e}")


def data_path(name: str) -> pathlib.Path:
    """Absolute path to a runtime/user-data file inside USER_DATA_DIR.

    All persisted state (memory, mood, quiet, reminders, history, owner profile,
    settings) resolves through here so the whole writable surface can be relocated
    with one env var and factory-reset in one place."""
    return USER_DATA_DIR / name


_IDENTITY_NAME_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9 '\-]{0,39}")


def identity_name(name) -> str | None:
    """Validate a person's name before it is used as a faces/voices directory name.

    Names come from Claude's tool calls, so anything spoken (or injected through
    a search result) can end up here. Only letters, digits, spaces, hyphens and
    apostrophes are allowed, at most 40 characters, so a name can never be
    "..", empty, or contain a path separator. Returns the cleaned name or None."""
    cleaned = " ".join(str(name or "").split())
    if not _IDENTITY_NAME_RE.fullmatch(cleaned) or not any(c.isalpha() for c in cleaned):
        return None
    return cleaned


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


def is_configured() -> bool:

    """Check if the appliance has completed initial setup (configured flag is True and Anthropic API key is set)."""
    if _SETTINGS.get("configured") is True:
        return True
    # If ANTHROPIC_API_KEY is non-empty, consider it configured
    if ANTHROPIC_API_KEY and len(ANTHROPIC_API_KEY.strip()) > 10:
        return True
    return False


def save_settings(new_settings: dict) -> None:
    """Merge and save new settings into USER_DATA_DIR/settings.json, updating module globals."""
    global _SETTINGS, ANTHROPIC_API_KEY, OPENAI_API_KEY, ELEVENLABS_API_KEY, ELEVENLABS_VOICE_ID, SKULL_NAME
    p = USER_DATA_DIR / "settings.json"
    current = _load_settings()
    current.update(new_settings)
    current["configured"] = True
    
    atomic_write(p, json.dumps(current, indent=2), mode=0o600)
    _SETTINGS = current
    
    # Update active globals
    if "ANTHROPIC_API_KEY" in current:
        ANTHROPIC_API_KEY = str(current["ANTHROPIC_API_KEY"])
    if "OPENAI_API_KEY" in current:
        OPENAI_API_KEY = str(current["OPENAI_API_KEY"])
    if "ELEVENLABS_API_KEY" in current:
        ELEVENLABS_API_KEY = str(current["ELEVENLABS_API_KEY"])
    if "SKULL_NAME" in current:
        SKULL_NAME = str(current["SKULL_NAME"])
    # Voice IDs are stored per personality (see ELEVENLABS_VOICE_ID below).
    voice_key = voice_id_setting_name(SKULL_NAME)
    if voice_key in current:
        ELEVENLABS_VOICE_ID = str(current[voice_key])


def save_owner_profile(data: dict) -> None:
    """Save updated owner profile data to USER_DATA_DIR/owner.json."""
    global _OWNER_PROFILE
    p = USER_DATA_DIR / "owner.json"
    atomic_write(p, json.dumps(data, indent=2), mode=0o600)
    _OWNER_PROFILE = data


def set_honorific(new_honorific: str) -> str:
    """Update preferred honorific/title in owner.json."""
    global _OWNER_PROFILE
    new_h = (new_honorific or "").strip()
    if not new_h:
        return "Please specify a valid honorific."
    profile = dict(_OWNER_PROFILE or {})
    profile["honorific"] = new_h
    profile["title"] = new_h
    save_owner_profile(profile)
    return f"Honorific updated to '{new_h}'. I will address you as {new_h} from now on."


def _cfg(key: str, default: str = "") -> str:
    """Value for a user-facing setting: env -> settings.json -> default."""
    v_env = os.getenv(key)
    if v_env is not None and str(v_env) != "":
        return str(v_env)
    v = _SETTINGS.get(key)
    if v is not None and str(v) != "":
        return str(v)
    return default


# ── Secrets / API keys (user-provided via the setup wizard) ──────────────────────
# Optional at import so the app starts with only the backends it actually uses
# configured (e.g. local Piper voice needs no ElevenLabs key). Each consumer raises
# a clear error on first use if its key is missing.
ANTHROPIC_API_KEY = _cfg("ANTHROPIC_API_KEY", "")
OPENAI_API_KEY = _cfg("OPENAI_API_KEY", "")
ELEVENLABS_API_KEY = _cfg("ELEVENLABS_API_KEY", "")
SKULL_NAME = _cfg("SKULL_NAME", "Omega-7")
from typing import Optional

def get_personality_key(name: Optional[str] = None) -> str:
    """Resolve a personality name (e.g. 'Omega-7', 'omega 7', 'omega-7') to its
    directory/module key under personalities/ (e.g. 'omega7')."""
    target = (name or SKULL_NAME or "Omega-7").strip().lower()
    raw_key = target.replace("-", "").replace(" ", "")
    base_dir = pathlib.Path(__file__).parent.parent / "personalities"
    if (base_dir / raw_key).exists():
        return raw_key
    if (base_dir / target).exists():
        return target
    if (base_dir / "omega7").exists():
        return "omega7"
    return "skull"

def _load_personality_config(name: str) -> dict:
    key = get_personality_key(name)
    base_dir = pathlib.Path(__file__).parent.parent / "personalities"
    p_dir = base_dir / key
    cfg_path = p_dir / "config.json"
    if cfg_path.exists():
        try:
            return json.loads(cfg_path.read_text())
        except Exception as e:
            print(f"[config] Error reading personality config {cfg_path}: {e}")
    return {}

PERSONALITY = _load_personality_config(SKULL_NAME)


def voice_id_setting_name(skull_name: str) -> str:
    """The setting that holds a personality's ElevenLabs voice, e.g.
    ELEVENLABS_VOICE_ID_OMEGA-7. Per personality so one .env / settings.json can
    carry a voice for each; a plain ELEVENLABS_VOICE_ID is not read."""
    return f"ELEVENLABS_VOICE_ID_{skull_name.upper()}"


ELEVENLABS_VOICE_ID = _cfg(voice_id_setting_name(SKULL_NAME), PERSONALITY.get("elevenlabs_voice_id", "21m00Tcm4TlvDq8ikWAM"))

# ── Bambu 3D Printer ─────────────────────────────────────────────────────────────
BAMBU_PRINTER_IP = _cfg("BAMBU_PRINTER_IP", "")
BAMBU_PRINTER_SERIAL = _cfg("BAMBU_PRINTER_SERIAL", "")
BAMBU_PRINTER_ACCESS_CODE = _cfg("BAMBU_PRINTER_ACCESS_CODE", "")

# Claude (Anthropic) powers the brain, idle utterances, memory extraction, and vision.
CLAUDE_MODEL = _cfg("CLAUDE_MODEL", "claude-sonnet-5-5")
# OpenAI speech-to-text model: whisper-1 (default) or gpt-4o-mini-transcribe (faster, more accurate).
STT_MODEL = _cfg("STT_MODEL", "whisper-1")
# Stream the recording to a realtime transcription session while it is captured,
# so the transcript is ready when the speaker stops (falls back to STT_MODEL).
STT_STREAMING = _cfg("STT_STREAMING", "true").lower() == "true"
STT_STREAMING_MODEL = _cfg("STT_STREAMING_MODEL", "gpt-4o-mini-transcribe")

# ── Text-to-speech ───────────────────────────────────────────────────────────────
# "piper" (local, free) or "elevenlabs" (cloud, quota-limited)
TTS_BACKEND = _cfg("TTS_BACKEND", "elevenlabs")
PIPER_MODEL_PATH = _cfg("PIPER_MODEL_PATH", "models/servoskull.onnx")
# ElevenLabs model. eleven_turbo_v2 is the default on purpose: its flatter, more
# synthetic reading suits a servo-skull better than the expressive generation does.
# The emotive build is one setting away — ELEVENLABS_MODEL=eleven_v4_turbo (or
# eleven_v3_conversational) performs the bracketed audio tags the phrases and the
# persona already carry, and everything downstream follows that one switch: tags are
# passed through instead of stripped, the persona is told it may use them, and the
# canned phrases re-voice themselves. On any other model the tags are stripped and
# never reach the voice, so they cost nothing while they sit unused.
ELEVENLABS_MODEL = _cfg("ELEVENLABS_MODEL", "eleven_turbo_v2")
# Pass the persona's audio tags through to ElevenLabs instead of stripping them.
# Turn off to get flat delivery from a tag-capable model without changing models.
ELEVENLABS_AUDIO_TAGS = _cfg("ELEVENLABS_AUDIO_TAGS", "true").lower() == "true"


def _voice_setting(name: str, personality_key: str) -> float | None:
    """A 0.0–1.0 ElevenLabs voice setting, or None to leave it to the voice itself.

    Unset is not the same as 0.5: with nothing sent, ElevenLabs applies the settings
    stored on the voice in its dashboard, which is where a tuned voice is tuned. A
    value here overrides that per request, so it is only sent when explicitly set."""
    raw = str(_cfg(name, PERSONALITY.get(personality_key, ""))).strip()
    if not raw:
        return None
    try:
        value = float(raw)
    except ValueError:
        print(f"[config] {name}={raw!r} is not a number; leaving it to the voice.")
        return None
    if not 0.0 <= value <= 1.0:
        print(f"[config] {name}={value} is outside 0.0-1.0; leaving it to the voice.")
        return None
    return value


# How much the delivery may vary between generations. Lower is more expressive and
# more responsive to the audio tags; higher holds a fixed baseline and can flatten
# into monotony. Eleven v4 kept only this and similarity — style and speed are gone,
# and pacing now comes from the script (ellipses, capitals, a [slowly] tag).
ELEVENLABS_STABILITY = _voice_setting("ELEVENLABS_STABILITY", "elevenlabs_stability")
# How closely the output tracks the reference voice. Higher follows the clone more
# strictly, sometimes at the cost of sounding natural.
ELEVENLABS_SIMILARITY = _voice_setting("ELEVENLABS_SIMILARITY", "elevenlabs_similarity")
# Wipe cached canned-phrase audio for one run after changing the ElevenLabs voice.
RESET_VOICE_CACHE = _cfg("RESET_VOICE_CACHE", "false").lower() == "true"

# ── Wake word (openWakeWord) ─────────────────────────────────────────────────────
# A built-in model name (e.g. "hey_jarvis") or a path to a custom .onnx model.
# Per personality, like the voice: WAKE_WORD_MODEL_OMEGA-7, WAKE_WORD_MODEL_JAX.
WAKE_WORD_MODEL = _cfg(f"WAKE_WORD_MODEL_{SKULL_NAME.upper()}", PERSONALITY.get("wake_word_model", "models/servitor.onnx"))
WAKE_WORD_THRESHOLD = float(_cfg("WAKE_WORD_THRESHOLD", "0.65"))
# Barge-in is still harder than waking a silent skull, but no longer because of the
# echo canceller — BARGE_IN_SOURCE below takes that out of the path. What remains is
# that the skull's own voice is additive interference in the raw capture, which costs
# the model real confidence even though it scores that voice alone at 0.001: measured
# on the unit, the summons that fires at 0.914 into silence peaked at 0.465 over
# playback. 0.40 left only 16% of headroom over a successful barge-in, so a quieter
# one or one from further off would have missed.
#
# 0.30 is affordable because the self-trigger risk is measured rather than guessed:
# 29 s of the skull's own speech tops out at 0.020 on this source, at every gain from
# 1x to 16x, which leaves a 15x margin — and a line that does contain the wake word
# turns barge-in off while it plays (main._wake_word_guard). Raise it if Omega-7
# starts cutting itself off, and check the saved clip's score before assuming the
# model is at fault.
WAKE_WORD_THRESHOLD_BARGE_IN = float(_cfg("WAKE_WORD_THRESHOLD_BARGE_IN", "0.30"))
# Which microphone the barge-in listener uses. Measured on this unit: the same
# summons scores 0.914 into silence and 0.09-0.21 while the skull is talking, on the
# echo-cancelled source. There is almost nothing to cancel -- the raw mic hears the
# skull's own speaker at only 4.3% peak -- but WebRTC's residual suppressor attenuates
# the whole near-end path whenever the reference is active, and a human cutting in
# goes with it. PipeWire's module exposes no control over that, and noise suppression,
# AGC and voice detection are already off.
#
# So barge-in listens to the raw source instead, where a human arrives unsuppressed.
# What stops the skull waking itself there is the wake-word model, not the canceller:
# 29 s of its own speech scored 0.020 at the top, at every gain from 1x to 16x, against
# a 0.40 threshold. Set to "" to fall back to the default (echo-cancelled) source.
BARGE_IN_SOURCE = _cfg(
    "BARGE_IN_SOURCE",
    "alsa_input.usb-C-Media_Electronics_Inc._USB_Audio_Device-00.mono-fallback",
).strip()
# The raw source does not get MIC_SOFT_GAIN, which PipeWire applies to the
# echo-cancelled source only, so the same lift is applied in software. PipeWire's
# volume is a cubic curve, so MIC_SOFT_GAIN 2.0 is about x8 linear; the skull's own
# voice still peaks at only 35% of full scale there, so nothing clips.
BARGE_IN_SOURCE_GAIN = float(_cfg("BARGE_IN_SOURCE_GAIN", "8.0"))



# ── Bluetooth ────────────────────────────────────────────────────────────────────
# "dbus" drives BlueZ through its own D-Bus API and holds the speaker as a desired
# state that a reconciler converges on: it is told the moment a link drops, and
# brings it back. "bluetoothctl" is the older path, which drove the interactive CLI
# through pexpect and ran once, so a speaker that dropped stayed dropped.
BLUETOOTH_BACKEND = _cfg("BLUETOOTH_BACKEND", "dbus").strip().lower()


def _resolve_input_device(raw: str) -> int:
    """Resolve a mic setting to a sounddevice input index.

    Accepts either a numeric index (e.g. "2") or a case-insensitive name substring
    (e.g. "USB"). Returns -1 (system default / PipeWire) when set to "-1" or
    unmatched, ensuring audio streams route through PipeWire rather than locking raw ALSA devices.
    """
    raw = (raw or "").strip()
    if raw == "" or raw == "-1" or raw.lower() in ("default", "pipewire", "none"):
        return -1
    try:
        import sounddevice as sd
        devices = sd.query_devices()
        try:
            val = int(raw)
            if val >= 0:
                return val
        except ValueError:
            for idx, dev in enumerate(devices):
                if dev.get("max_input_channels", 0) > 0 and raw.lower() in dev["name"].lower():
                    print(f"[config] MIC_DEVICE_INDEX '{raw}' matched device {idx}: {dev['name']!r}")
                    return idx
    except Exception as e:
        print(f"[config] mic resolution error ({e})")
    return -1


# ── Audio devices ────────────────────────────────────────────────────────────────
MIC_DEVICE_INDEX = _resolve_input_device(_cfg("MIC_DEVICE_INDEX", "-1"))
_raw_out = int(_cfg("AUDIO_OUTPUT_DEVICE", "-1"))
AUDIO_OUTPUT_DEVICE = _raw_out if _raw_out >= 0 else None
# Pinned device for TTS/SFX — stays on the skull's own speaker even when BT is the PulseAudio default
_raw_voice_out = int(_cfg("VOICE_OUTPUT_DEVICE", str(_raw_out)))
VOICE_OUTPUT_DEVICE = _raw_voice_out if _raw_voice_out >= 0 else None
# Set to true to print per-chunk RMS values during recording
AUDIO_DEBUG = os.getenv("AUDIO_DEBUG", "false").lower() == "true"
# Auto-listen for follow-up recording only when the spoken response ends with a question
AUTO_LISTEN_ON_QUESTION = _cfg("AUTO_LISTEN_ON_QUESTION", "true").lower() == "true"



# ── Spotify (optional music control; Premium required) ───────────────────────────
SPOTIFY_CLIENT_ID = _cfg("SPOTIFY_CLIENT_ID", "")
SPOTIFY_CLIENT_SECRET = _cfg("SPOTIFY_CLIENT_SECRET", "")
SPOTIFY_REDIRECT_URI = _cfg("SPOTIFY_REDIRECT_URI", "http://127.0.0.1:8888/callback")
# Spotify Connect device name for local playback (Raspotify running on the Pi)
SPOTIFY_DEVICE_NAME = _cfg("SPOTIFY_DEVICE_NAME", "Omega-7")

# ── Google Home / Chromecast audio (optional) ────────────────────────────────────
GOOGLE_HOME_DEVICE = _cfg("GOOGLE_HOME_DEVICE", "")
# Casting is opt-in on macOS (dev) and opt-out on Linux/Pi, matching the
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
CAMERA_ROTATION = int(os.getenv("CAMERA_ROTATION", "270"))  # 0, 90, 180, 270 (degrees clockwise)
# Fine tilt correction applied after CAMERA_ROTATION, in degrees counter-clockwise
# (OpenCV convention; use a negative value to rotate clockwise). 0 = no correction.
CAMERA_FINE_ROTATION = float(os.getenv("CAMERA_FINE_ROTATION", "0"))

# ── Proximity trigger — VL53L1X time-of-flight sensor (I2C, optional) ─────────────
# When present, the camera fires vision on genuine physical approach instead of
# frame-difference motion — it doesn't false-trip on lighting/auto-exposure and it
# works in a dark room (a laser rangefinder needs no ambient light). If disabled or
# the sensor isn't found on the bus, camera.py transparently falls back to motion
# detection.
#
# Wiring (DWEII VL53L1X breakout → Pi 5 40-pin header, I2C1):
#   VIN → 3V3 (pin 1)   GND → GND (pin 6)   SDA → GPIO2 (pin 3)   SCL → GPIO3 (pin 5)
PROXIMITY_ENABLED = _cfg("PROXIMITY_ENABLED", "false").lower() == "true"
# Fire a vision call when a target is detected within this many centimetres.
PROXIMITY_THRESHOLD_CM = int(os.getenv("PROXIMITY_THRESHOLD_CM", "150"))
# The morning greeting fires when someone is within this range and a face is visible.
# Sized for a person seated at the desk, which is farther than the vision trigger.
MORNING_GREETING_DISTANCE_CM = int(os.getenv("MORNING_GREETING_DISTANCE_CM", "300"))
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


# ── Eye LEDs (Individually Addressable WS2812B RGB LEDs) ──────────────────────────
# 2 WS2812B LEDs (Left Eye, Right Eye; 3rd lens housing is mounted with the Camera).
# Data line uses GPIO 18 (Pin 12 / PWM0) stepped up from 3.3V to 5V via level shifter.
EYE_LED_PIN = int(os.getenv("EYE_LED_PIN", "18"))
EYE_LED_COUNT = int(os.getenv("EYE_LED_COUNT", "2"))

# Legacy GPIO PWM pins (kept for fallback compatibility)
LED_PIN_LEFT = int(os.getenv("LED_PIN_LEFT", "22"))
LED_PIN_CENTER = int(os.getenv("LED_PIN_CENTER", "23"))
LED_PIN_RIGHT = int(os.getenv("LED_PIN_RIGHT", "27"))

# ── Candle LEDs (self-flickering, GPIO-switched via transistor) — optional ────────
# The EDGELEC 2V flicker LEDs atop the skull flicker on their own internal IC; the
# GPIO only gates them on/off through a 2N2222 low-side switch, so the skull lights
# its candles when it wakes and snuffs them on shutdown. Disabled by default so non-Pi
# dev hosts and un-wired Pis are unaffected; set CANDLE_ENABLED=true in .env when
# wired. Current flows from the 5V rail through the transistor, not the GPIO, so the
# candle count is limited only by the rail — not the Pi's per-pin current budget.
CANDLE_ENABLED = _cfg("CANDLE_ENABLED", "false").lower() == "true"
CANDLE_PIN = int(os.getenv("CANDLE_PIN", "17"))

# ── Face display (GC9A01 1.28" round IPS, 240x240, 4-wire SPI) ───────────────────
# Optional "machine-spirit" eye/face display. Disabled by default so non-Pi dev
# hosts and displayless Pis are unaffected; set DISPLAY_ENABLED=true in .env on the
# rig that has the panel wired.
#
# Audio is handled by a USB sound card (Ugreen), so the GPIO header is otherwise free
# except the eye LEDs (22/23/27) — SPI0 is fully available for the panel.
#
# Wiring (BCM):
#   VCC->3V3 (pin 17)   GND->GND (pin 20)
#   SCL(SCK)->GPIO11 (pin 23)   SDA(MOSI)->GPIO10 (pin 19)   CS->GPIO8 (pin 24)
#   DC->GPIO25 (pin 22)   RES->GPIO24 (pin 18)   BLK->GPIO12 (pin 32, or tie to 3V3 and set DISPLAY_BL_PIN=-1)
DISPLAY_ENABLED = os.getenv("DISPLAY_ENABLED", "false").lower() == "true"
DISPLAY_SPI_BUS = int(os.getenv("DISPLAY_SPI_BUS", "0"))       # spidev<bus>.<device>
DISPLAY_SPI_DEVICE = int(os.getenv("DISPLAY_SPI_DEVICE", "0")) # 0 -> CE0/GPIO8
DISPLAY_SPI_HZ = int(os.getenv("DISPLAY_SPI_HZ", "40000000"))  # 40 MHz; lower if flaky
DISPLAY_DC_PIN = int(os.getenv("DISPLAY_DC_PIN", "25"))
DISPLAY_RST_PIN = int(os.getenv("DISPLAY_RST_PIN", "24"))
DISPLAY_BL_PIN = int(os.getenv("DISPLAY_BL_PIN", "12"))        # GPIO 12 (pin 32) -1 if BLK tied to 3V3
DISPLAY_ROTATION = int(os.getenv("DISPLAY_ROTATION", "0"))     # 0/90/180/270
DISPLAY_FINE_ROTATION = float(_cfg("DISPLAY_FINE_ROTATION", "18.0"))  # software rotation offset (degrees, positive = clockwise)
DISPLAY_IDLE_TIMEOUT = float(_cfg("DISPLAY_IDLE_TIMEOUT", "300.0"))  # seconds before showing idle animations (default: 5 minutes)
# Power saving (the Pi's supply is marginal): during sleep hours an idle panel is put
# to sleep (SLPIN + backlight off) instead of running screensavers all night; when
# the rangefinder has seen nobody move for DISPLAY_PRESENCE_TIMEOUT, idle/screensaver
# rendering drops to DISPLAY_IDLE_FPS; static screens (text, images, update progress)
# refresh at DISPLAY_STATIC_FPS and are only re-sent over SPI when they change.
DISPLAY_SLEEP_IN_QUIET_HOURS = _cfg("DISPLAY_SLEEP_IN_QUIET_HOURS", "true").lower() == "true"
DISPLAY_PRESENCE_TIMEOUT = float(_cfg("DISPLAY_PRESENCE_TIMEOUT", "1200.0"))  # seconds without rangefinder change
DISPLAY_IDLE_FPS = float(_cfg("DISPLAY_IDLE_FPS", "10.0"))      # screensaver rate when nobody is around
DISPLAY_STATIC_FPS = float(_cfg("DISPLAY_STATIC_FPS", "2.0"))   # refresh rate for static screens


def set_display_rotation(degrees: float, relative: bool = False) -> str:
    """Adjust or set the fine rotation offset of the eye display in degrees (positive = clockwise)."""
    global DISPLAY_FINE_ROTATION
    if relative:
        new_val = (DISPLAY_FINE_ROTATION + degrees) % 360
        if new_val > 180:
            new_val -= 360
    else:
        new_val = degrees
    
    DISPLAY_FINE_ROTATION = round(new_val, 1)
    _update_env_var("DISPLAY_FINE_ROTATION", str(DISPLAY_FINE_ROTATION))
            
    return f"Display rotation set to {DISPLAY_FINE_ROTATION} degrees."


# ── The Bard's Tale (games/bardstale) — Omega-7 plays it himself on an emulated Apple IIe ──
# hybrid: a rule-based autopilot plays; the model only voices commentary and handles
# rare or unfamiliar screens (cents per hour). llm: the model decides every move, one
# vision call per turn (Sonnet: roughly $3–4 per hour; Haiku is cheaper but wanders).
BARDSTALE_MODE = _cfg("BARDSTALE_MODE", "hybrid").lower()
BARDSTALE_MODEL = _cfg("BARDSTALE_MODEL", "claude-sonnet-5")      # vision turns (llm mode, rescues)
BARDSTALE_NARRATOR_MODEL = _cfg("BARDSTALE_NARRATOR_MODEL", "claude-haiku-4-5-20251001")
BARDSTALE_STEP_SECS = float(_cfg("BARDSTALE_STEP_SECS", "0.8"))       # autopilot pace, for watchability
BARDSTALE_MAX_MINUTES = float(_cfg("BARDSTALE_MAX_MINUTES", "120"))   # a session stops (and saves) after this; 0 = no limit
BARDSTALE_NARRATE_SECS = float(_cfg("BARDSTALE_NARRATE_SECS", "45"))  # minimum gap between spoken comments
BARDSTALE_ROMPATH = _cfg("BARDSTALE_ROMPATH", "")                    # Apple IIe ROM zips; default ~/.mame/roms


# ── Internal temperature monitoring (Raspberry Pi only) ──────────────────────────
# The skull watches its SoC temperature and speaks a warning when it climbs too high.
# The Pi 5 begins soft-throttling around 80°C and hard-throttles ~85°C, so the
# default warns at 80 and re-arms once it cools below 72. No-op on non-Pi hosts
# (no thermal sensor). Set TEMP_MONITOR_ENABLED=false to disable entirely.
TEMP_MONITOR_ENABLED = os.getenv("TEMP_MONITOR_ENABLED", "true").lower() == "true"
WEB_SERVER_ENABLED = os.getenv("WEB_SERVER_ENABLED", "true").lower() == "true"
WEB_SERVER_PORT = int(os.getenv("WEB_SERVER_PORT", "8080"))
TEMP_WARN_THRESHOLD = float(os.getenv("TEMP_WARN_THRESHOLD", "80"))    # °C — warn at/above this
TEMP_CLEAR_THRESHOLD = float(os.getenv("TEMP_CLEAR_THRESHOLD", "72"))  # °C — re-arm once below this
TEMP_CHECK_INTERVAL = int(os.getenv("TEMP_CHECK_INTERVAL", "30"))      # seconds between readings
TEMP_WARN_COOLDOWN = int(os.getenv("TEMP_WARN_COOLDOWN", "300"))       # min seconds between repeat warnings

# ── Power-supply monitor (Raspberry Pi) ──────────────────────────────────────────
# Polls the firmware's under-voltage flag (vcgencmd get_throttled). Brown-outs crash
# the Pi and corrupt files mid-write, so every event is logged and the skull warns
# aloud (outside sleep hours, at most once per cooldown). No-op off the Pi.
POWER_MONITOR_ENABLED = os.getenv("POWER_MONITOR_ENABLED", "true").lower() == "true"
POWER_CHECK_INTERVAL = float(os.getenv("POWER_CHECK_INTERVAL", "5"))        # seconds between checks
POWER_WARN_COOLDOWN = int(os.getenv("POWER_WARN_COOLDOWN", "3600"))         # min seconds between spoken warnings

# ── Conversation history ─────────────────────────────────────────────────────────
# Stored inside USER_DATA_DIR. HISTORY_FILE may be a bare filename or an absolute path.
HISTORY_FILE = os.getenv("HISTORY_FILE", f"history_{get_personality_key()}.json")
# Maximum number of messages (turns) to keep in the short-term conversation history.
# 60 messages corresponds to 30 full back-and-forth conversation exchanges.
HISTORY_LIMIT = int(os.getenv("HISTORY_LIMIT", "60"))

# How long to record after wake word (seconds)
RECORD_SECONDS = 10
# Silence threshold (RMS). Used both to stop recording early and to decide whether
# any speech occurred at all — capture quieter than this is discarded as silence.
# LOWER = more sensitive to quiet speech (but more prone to picking up background
# noise); raise it if it starts transcribing ambient hum. Recorder floor is ~300.
SILENCE_THRESHOLD = int(_cfg("SILENCE_THRESHOLD", "180"))
# A wake followed by near-total silence was a false trigger on ambient noise, not a
# summons. Below this fraction of SILENCE_THRESHOLD nobody spoke at all, so the skull
# stays quiet instead of announcing itself to an empty room; above it, someone spoke
# too quietly and still deserves an answer.
FALSE_WAKE_RMS_RATIO = float(_cfg("FALSE_WAKE_RMS_RATIO", "0.55"))
# Save the ~2 s of audio behind every wake detection. True and false wake scores
# overlap almost completely, so no threshold separates them; retraining the model
# on the room's own false triggers is the only real fix, and that needs the audio.
WAKE_CAPTURE = _cfg("WAKE_CAPTURE", "false").strip().lower() in ("1", "true", "yes", "on")
WAKE_CAPTURE_DIR = _cfg("WAKE_CAPTURE_DIR", str(USER_DATA_DIR / "wake_clips"))
# With capture on, also keep the clips that scored close but did not fire. Picking
# a barge-in threshold means knowing what the summons that failed actually scored,
# and a miss leaves no trace otherwise — the log only ever records successes.
WAKE_CAPTURE_FLOOR = float(_cfg("WAKE_CAPTURE_FLOOR", "0.25"))
# Software gain applied to the microphone as PipeWire's source volume (1.0 = none).
# The USB codec's analog gain is already at its top and speech still peaked near 5%
# of full scale, which starved the VAD and the transcribers. PipeWire's volume
# number follows a cubic curve, so 2.0 is about x8 linear (+18 dB): normal speech
# peaks around 20-30% (it was 10-14% at 1.6), the noise floor (RMS ~70) stays far
# below SILENCE_THRESHOLD, and loud speech still doesn't clip. Measured on the
# unit: 1.0 -> RMS 9, 1.6 -> 37, 2.0 -> 69, 4.0 -> 87 (capped).
MIC_SOFT_GAIN = float(_cfg("MIC_SOFT_GAIN", "2.0"))
SILENCE_DURATION = float(_cfg("SILENCE_DURATION", "1.2"))  # seconds of silence that end a command
# Voice activity detection (models/silero_vad.onnx). With it, a command ends
# VAD_END_SILENCE seconds after the speaker stops; SILENCE_DURATION then only
# bounds how long to wait for them to start. Falls back to RMS silence if off.
VAD_ENABLED = _cfg("VAD_ENABLED", "true").lower() == "true"
VAD_THRESHOLD = float(_cfg("VAD_THRESHOLD", "0.5"))     # speech probability that counts as talking
VAD_END_SILENCE = float(_cfg("VAD_END_SILENCE", "0.7"))  # seconds of non-speech that end a command


# Sensitivity is the inverse of the threshold: asking the skull to listen harder
# LOWERS the number. The arithmetic lives here so the spoken intent in main.py and
# the model's set_wake_word_sensitivity tool cannot drift apart — the tool had been
# the only way to reach it, and the model would narrate the change without making it.
WAKE_SENSITIVITY_STEP = 0.10
WAKE_THRESHOLD_FLOOR = 0.25   # below this it wakes on room noise
WAKE_THRESHOLD_CEILING = 0.90
WAKE_THRESHOLD_DEFAULT = 0.65


def set_wake_word_threshold(threshold: float) -> str:
    """Set the idle wake-word threshold outright and persist it. Returns a spoken line."""
    global WAKE_WORD_THRESHOLD
    value = max(WAKE_THRESHOLD_FLOOR, min(WAKE_THRESHOLD_CEILING, float(threshold)))
    WAKE_WORD_THRESHOLD = round(value, 2)
    _update_env_var("WAKE_WORD_THRESHOLD", f"{WAKE_WORD_THRESHOLD:.2f}")
    if WAKE_WORD_THRESHOLD < WAKE_THRESHOLD_DEFAULT:
        how = "more sensitive — it will wake on a quieter or less exact summons"
    elif WAKE_WORD_THRESHOLD > WAKE_THRESHOLD_DEFAULT:
        how = "less sensitive — fewer false wakes, and it will want a clearer summons"
    else:
        how = "the standard setting"
    return f"Wake word threshold set to {WAKE_WORD_THRESHOLD:.2f}: {how}."


def adjust_wake_word_sensitivity(direction: str | None = None, threshold: float | None = None,
                                 level: str | None = None) -> str:
    """Resolve a sensitivity request to a threshold and apply it.

    `threshold` is absolute; `direction` is "more"/"less" and steps from where it is
    now; `level` is "high"/"medium"/"low". Returns the line to speak.
    """
    if threshold is not None:
        return set_wake_word_threshold(threshold)
    if level:
        lvl = str(level).lower().strip()
        # A named level is an absolute setting, not a step. "High" lands well clear of
        # the floor: at the floor itself the room's own noise wakes the skull.
        named = {"high": 0.45, "more": 0.45, "sensitive": 0.45, "more_sensitive": 0.45,
                 "low": 0.80, "less": 0.80, "strict": 0.80, "less_sensitive": 0.80,
                 "medium": WAKE_THRESHOLD_DEFAULT, "default": WAKE_THRESHOLD_DEFAULT,
                 "normal": WAKE_THRESHOLD_DEFAULT, "standard": WAKE_THRESHOLD_DEFAULT,
                 "maximum": WAKE_THRESHOLD_FLOOR, "max": WAKE_THRESHOLD_FLOOR,
                 "minimum": WAKE_THRESHOLD_CEILING, "min": WAKE_THRESHOLD_CEILING}
        if lvl in named:
            return set_wake_word_threshold(named[lvl])
    if direction == "more":
        return set_wake_word_threshold(WAKE_WORD_THRESHOLD - WAKE_SENSITIVITY_STEP)
    if direction == "less":
        return set_wake_word_threshold(WAKE_WORD_THRESHOLD + WAKE_SENSITIVITY_STEP)
    return (f"Wake word threshold is {WAKE_WORD_THRESHOLD:.2f}. Say more or less sensitive, "
            f"or name a threshold between {WAKE_THRESHOLD_FLOOR:.2f} and {WAKE_THRESHOLD_CEILING:.2f}.")


# Microphone sensitivity inverts the same way the wake threshold does: asking the
# skull to hear quieter speech LOWERS the RMS floor below which capture is treated as
# silence. These bounds are set around the shipped default rather than the ones the
# model's tool used to carry (step 200, floor 200, "medium" 500), which predate the
# move to a 180 floor and would have made any adjustment a drastic one.
MIC_SENSITIVITY_STEP = 40
SILENCE_THRESHOLD_FLOOR = 80      # below this the recorder triggers on room hum
SILENCE_THRESHOLD_CEILING = 600
SILENCE_THRESHOLD_DEFAULT = 180


def set_silence_threshold(threshold: float) -> str:
    """Set the RMS silence floor outright and persist it. Returns a spoken line."""
    global SILENCE_THRESHOLD
    value = max(SILENCE_THRESHOLD_FLOOR, min(SILENCE_THRESHOLD_CEILING, int(round(float(threshold)))))
    SILENCE_THRESHOLD = value
    _update_env_var("SILENCE_THRESHOLD", str(SILENCE_THRESHOLD))
    if SILENCE_THRESHOLD < SILENCE_THRESHOLD_DEFAULT:
        how = "more sensitive — it will pick up quieter speech, and more of the room"
    elif SILENCE_THRESHOLD > SILENCE_THRESHOLD_DEFAULT:
        how = "less sensitive — it will ignore more background noise, and quiet speech with it"
    else:
        how = "the standard setting"
    return f"Microphone silence threshold set to {SILENCE_THRESHOLD}: {how}."


def adjust_mic_sensitivity(direction: str | None = None, threshold: float | None = None,
                           level: str | None = None) -> str:
    """Resolve a microphone sensitivity request to an RMS floor and apply it.

    Mirrors adjust_wake_word_sensitivity: `threshold` is absolute, `direction` is
    "more"/"less" and steps from here, `level` is a named absolute setting.
    """
    if threshold is not None:
        return set_silence_threshold(threshold)
    if level:
        lvl = str(level).lower().strip()
        named = {"high": 120, "more": 120, "sensitive": 120, "more_sensitive": 120,
                 "low": 320, "less": 320, "strict": 320, "less_sensitive": 320,
                 "quiet": 320, "noise": 320,
                 "medium": SILENCE_THRESHOLD_DEFAULT, "default": SILENCE_THRESHOLD_DEFAULT,
                 "normal": SILENCE_THRESHOLD_DEFAULT, "standard": SILENCE_THRESHOLD_DEFAULT,
                 "maximum": SILENCE_THRESHOLD_FLOOR, "max": SILENCE_THRESHOLD_FLOOR,
                 "minimum": SILENCE_THRESHOLD_CEILING, "min": SILENCE_THRESHOLD_CEILING}
        if lvl in named:
            return set_silence_threshold(named[lvl])
    if direction == "more":
        return set_silence_threshold(SILENCE_THRESHOLD - MIC_SENSITIVITY_STEP)
    if direction == "less":
        return set_silence_threshold(SILENCE_THRESHOLD + MIC_SENSITIVITY_STEP)
    return (f"Microphone silence threshold is {SILENCE_THRESHOLD}. Say more or less sensitive, "
            f"or name a value between {SILENCE_THRESHOLD_FLOOR} and {SILENCE_THRESHOLD_CEILING}.")


def set_silence_duration(seconds: float) -> str:
    """Set the silence wait duration after speaking (in seconds) and persist to .env."""
    global SILENCE_DURATION
    val = max(0.5, min(10.0, float(seconds)))
    SILENCE_DURATION = round(val, 1)
    
    _update_env_var("SILENCE_DURATION", str(SILENCE_DURATION))
    return f"Voice wait duration set to {SILENCE_DURATION} seconds."

# Speaker identification GMM score threshold to reject untrained/unknown voices.
# Since training samples average -52.0 to -53.0 on 13-dim MFCCs, a default of -60.0
# provides a secure margin for clean matches while successfully rejecting noise/strangers.
# Only used if no background model could be trained; normally speaker_id calibrates
# a likelihood-ratio threshold against the background model when it trains.
SPEAKER_ID_THRESHOLD = float(_cfg("SPEAKER_ID_THRESHOLD", "-60.0"))


# ── Persona (character = product data; owner profile = user data) ─────────────────
# The servo-skull character and all tool-usage instructions live in the shipped
# persona template; the owner's personal details come from owner.json (written by
# the setup wizard). See core/persona.py.
from core import persona as _persona  # noqa: E402  (needs USER_DATA_DIR above)

# The skull's own name — owner-settable at setup; defaults to the product name.
# Woven into the persona, spoken boot/barge-in lines, and the vision/STT prompts.
SKULL_NAME = _cfg("SKULL_NAME", "Omega-7")

_OWNER_PROFILE = _persona.load_owner(USER_DATA_DIR)
SYSTEM_PROMPT = _persona.build_system_prompt(_OWNER_PROFILE, SKULL_NAME)
# Owner location (e.g. "City, State") — drives localized idle news scopes.
OWNER_LOCATION = _persona.owner_location(_OWNER_PROFILE)


# ── Spoken Phrases ─────────────────────────────────────────────────────────────
WAKE_PHRASES = PERSONALITY.get("wake_phrases", [])
COGITATION_PHRASES = PERSONALITY.get("cogitation_phrases", [])
SEARCH_PHRASES = PERSONALITY.get("search_phrases", [])
ACK_PHRASES = PERSONALITY.get("ack_phrases", [])
SILENCE_PHRASES = PERSONALITY.get("silence_phrases", [])

# ── Display and Animation Settings ──────────────────────────────────────────
# The render loop now paces accurately; the old loop only achieved ~14-15 fps, so
# 15 keeps the same look without doubling CPU/SPI load (raise for smoother motion).
DISPLAY_FPS = float(_cfg("DISPLAY_FPS", "15"))
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
