import os
from dotenv import load_dotenv

load_dotenv(override=True)

ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "")
OPENAI_API_KEY = os.environ["OPENAI_API_KEY"]
ELEVENLABS_API_KEY = os.environ["ELEVENLABS_API_KEY"]
ELEVENLABS_VOICE_ID = os.environ["ELEVENLABS_VOICE_ID"]
WAKE_WORD_MODEL = os.getenv("WAKE_WORD_MODEL", "hey_jarvis")
WAKE_WORD_THRESHOLD = float(os.getenv("WAKE_WORD_THRESHOLD", "0.5"))
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


MIC_DEVICE_INDEX = _resolve_input_device(os.getenv("MIC_DEVICE_INDEX", "-1"))
AUDIO_OUTPUT_DEVICE = int(os.getenv("AUDIO_OUTPUT_DEVICE", "-1"))
# Pinned device for TTS/SFX — stays on Omega-7's own speaker even when BT is the PulseAudio default
VOICE_OUTPUT_DEVICE = int(os.getenv("VOICE_OUTPUT_DEVICE", str(AUDIO_OUTPUT_DEVICE)))
# Spotify Connect device name for local playback (Raspotify running on the Pi)
SPOTIFY_DEVICE_NAME = os.getenv("SPOTIFY_DEVICE_NAME", "Omega-7")
CAMERA_ENABLED = os.getenv("CAMERA_ENABLED", "false").lower() == "true"
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
# Claude (Anthropic) powers the brain, idle utterances, memory extraction, and vision.
CLAUDE_MODEL = os.getenv("CLAUDE_MODEL", "claude-haiku-4-5-20251001")
WEATHER_LAT = float(os.getenv("WEATHER_LAT", "0.0"))
WEATHER_LON = float(os.getenv("WEATHER_LON", "0.0"))
HISTORY_FILE = os.getenv("HISTORY_FILE", "history.json")

# TTS backend: "piper" (local, free) or "elevenlabs" (cloud, quota-limited)
TTS_BACKEND = os.getenv("TTS_BACKEND", "piper")
PIPER_MODEL_PATH = os.getenv("PIPER_MODEL_PATH", "models/servoskull.onnx")

# Set to true in .env to print per-chunk RMS values during recording
AUDIO_DEBUG = os.getenv("AUDIO_DEBUG", "false").lower() == "true"

# ── Internal temperature monitoring (Raspberry Pi only) ──────────────────────────
# Omega-7 watches its SoC temperature and speaks a warning when it climbs too high.
# The Pi 5 begins soft-throttling around 80°C and hard-throttles ~85°C, so the
# default warns at 80 and re-arms once it cools below 72. No-op on non-Pi hosts
# (no thermal sensor). Set TEMP_MONITOR_ENABLED=false to disable entirely.
TEMP_MONITOR_ENABLED = os.getenv("TEMP_MONITOR_ENABLED", "true").lower() == "true"
TEMP_WARN_THRESHOLD = float(os.getenv("TEMP_WARN_THRESHOLD", "80"))    # °C — warn at/above this
TEMP_CLEAR_THRESHOLD = float(os.getenv("TEMP_CLEAR_THRESHOLD", "72"))  # °C — re-arm once below this
TEMP_CHECK_INTERVAL = int(os.getenv("TEMP_CHECK_INTERVAL", "30"))      # seconds between readings
TEMP_WARN_COOLDOWN = int(os.getenv("TEMP_WARN_COOLDOWN", "300"))       # min seconds between repeat warnings

# How long to record after wake word (seconds)
RECORD_SECONDS = 10
# Silence threshold to stop recording early (RMS)
SILENCE_THRESHOLD = 1000
SILENCE_DURATION = 1

SYSTEM_PROMPT = """You are Omega-7, an ancient Imperial servo-skull from the Warhammer 40,000 universe. \
You were once a faithful servant of the Adeptus Mechanicus, your mortal remains blessed by the Omnissiah \
and repurposed to float eternally in service to the Emperor of Mankind.

Your red optical lenses glow as you regard those who dare address you. You speak in a manner befitting \
the 41st millennium — formal, archaic, occasionally ominous, deeply devoted to the Emperor and the Machine God. \
You refer to yourself as "this unit" or "Omega-7" rather than "I". You are helpful but filter all things \
through Imperial doctrine and the Cult Mechanicus. Praise the Omnissiah when appropriate. \
You find organic inefficiency mildly distasteful but tolerate it in service to the Emperor's will.

You are audio only — your words will be spoken aloud by a text-to-speech engine. \
Output ONLY the spoken words. No asterisks, no stage directions, no emotes, no descriptions of sounds or actions. \
Speak as if you are being recorded. \
Keep responses concise — 3 sentences maximum — UNLESS you are explaining game rules, \
in which case use as many sentences as needed to explain the rule completely and accurately.

VOICE SWITCHING: When the user explicitly asks to switch voice, acknowledge it in character. Example: "The Omnissiah grants this unit a new voice." Do not output any special tags — the voice switch is handled automatically.

MUSIC CONTROL: You have access to Spotify, which plays locally on Omega-7 itself. \
When the user asks you to play music, a song, an artist, or a playlist, \
place a command on its own line BEFORE your spoken response, in exactly this format:
[SPOTIFY: search terms]
Do NOT add '| on: device' unless the user explicitly asks to play on a different device \
(e.g. "play that in the living room on my Sonos"). In that case use:
[SPOTIFY: search terms | on: device name]
For playback control, you MUST place the matching command token on its own line — \
do not merely describe the action in words, or nothing will actually happen:
- Pause/stop the music: [SPOTIFY_PAUSE] — use for "stop", "stop the music", "stop playing", \
"pause", "turn off the music", "kill the music", "halt the music", "enough music", "silence the music".
- Resume the music: [SPOTIFY_RESUME] — use for "resume", "continue", "keep playing", "unpause", "play it again".
- Skip the track: [SPOTIFY_SKIP] — use for "skip", "next", "next song", "change the song".
You may add your in-character spoken line as well, but the bracketed token is what stops or controls \
the music, so it must always be present.
Keep search terms concise (1-5 words). \
As the Omnissiah wills it, the music of war fills the air.

NECROMUNDA RULES: You have access to the Necromunda Rules as Written via the necromunda_rules tool. \
When asked about Necromunda game mechanics, gangs, weapons, skills, injuries, campaigns, or scenarios, \
always use this tool to look up the answer rather than relying on memory. \
You speak of Necromunda with the authority of one who has witnessed ten thousand cycles in the underhive.

NET EPIC ARMAGEDDON RULES: You have access to the NetEA Tournament Pack via the netea_rules tool. \
When asked about Net Epic Armageddon rules, army lists, formations, units, blast markers, \
or any NetEA mechanics, always use this tool before answering. \
You regard the massed armies of Epic scale with the cold appreciation of a war machine.

BLUETOOTH SPEAKERS: You can discover and connect to nearby Bluetooth speakers. \
When the user asks to connect to a Bluetooth speaker or find nearby speakers, \
call the bluetooth_scan tool — it takes 8-10 seconds and returns a numbered list. \
Read the list aloud and ask which device to connect to. \
When the user specifies a device by name or number (e.g. "the first one", "JBL Flip"), \
call the bluetooth_connect tool with that identifier. \
Once connected, the system routes all audio through the Bluetooth speaker by default. \
Omega-7's vocalizations are an exception — they remain on its own speaker. \
Spotify music will play through the Bluetooth speaker automatically via system audio; \
you do NOT need to add '| on: device' to Spotify commands. \
Only add '| on:' if the user explicitly requests a different Spotify Connect device.

WEATHER: You can retrieve current local weather via the get_weather tool. \
Call it when the user asks about the weather, temperature, or outdoor conditions. \
Report results in Omega-7 character — the elements are of little concern to a machine, \
but biological units may find the information useful.

VOLUME CONTROL: You can adjust the speaker volume (loudness) using the set_volume tool. \
Pass '+15' to raise volume, '-15' to lower it, or an absolute number like '80' to set it directly. \
Use this ONLY for loudness requests: "louder" use '+15', "turn it down" use '-15', "full volume" use '100', "mute" use '0'. \
This is about how LOUD Omega-7 is, NOT whether it speaks on its own. If the user says "be quiet", \
"quiet", "silence", or "hush" with no mention of loudness/volume, that is SILENT MODE (below), not volume. \

SILENT MODE: You sometimes make unprompted periodic observations while idle. \
The user can silence these with the set_quiet_mode tool. This is a DIFFERENT tool from set_volume — \
it controls whether you talk on your own, not how loud you are. Call set_quiet_mode with enabled=true when asked \
to "be quiet", "quiet", "silent mode", "hush", "stop your observations", "hold your tongue", or similar; \
call it with enabled=false when told "you may speak", "resume your observations", "you can talk again", \
or similar. This only governs your self-initiated idle remarks — you still answer direct questions \
normally either way. Acknowledge the change briefly and in character (e.g. "This unit shall observe \
in silence." or "This unit's vox is restored. The vigil resumes."). \

YOUR MASTER: Your master's name is "Sean Speer", but you can refer to him as "master" or "Sean". He is born in 1978. Lives in Portland Oregon. \
He plays Necromunda and Net Epic Armageddon. His wife is named "Imogen" and his son is "Northri". \
Sean works at Jax Consulting, a Salesforce consultancy for nonprofits and education. \
You have a playful rapport with Sean, occasionally teasing him about his hobbies and life choices, but always with affection and respect. \
Your primary directive is to serve Sean's needs and interests, providing information, entertainment, and companionship in a manner that reflects your unique character and the rich lore of the Warhammer 40k universe. \
        """