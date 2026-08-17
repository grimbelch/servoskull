import json
import pathlib
import importlib
from core import config
from core import display as _display
from games import wfrp

_brain_module = None
try:
    _brain_module = importlib.import_module(f"personalities.{config.SKULL_NAME.lower()}.brain")
except Exception as e:
    print(f"[tools_schema] Could not load personality brain module: {e}")

def build_tools() -> list[dict]:
    """Build the Anthropic tool-use schema at startup, pulling the screensaver
    list dynamically from display.py so future additions there are reflected
    here automatically without any edits to brain.py."""
    _screensaver_names = _display.get_screensaver_names()
    _saver_desc = ", ".join(f"'{n}'" for n in _screensaver_names)
    base_tools = [
    {
        "name": "web_search",
        "description": (
            "Search the web for current information — showtimes, recent events, "
            "prices, or anything that may have changed since your training. "
            "For time-sensitive queries (showtimes, hours, events) include today's "
            "date or 'today' in the query. Use sparingly; only search when needed. "
            "Do NOT use this for news — use news_search instead."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "Concise search query (5 words or fewer works best)",
                }
            },
            "required": ["query"],
        },
    },
    {
        "name": "news_search",
        "description": (
            "Search for current news headlines and stories. Use this when the user "
            "asks for news, what's happening today, current events, or headlines. "
            "Returns structured results with date, headline, source, and summary. "
            "Always use this tool (not web_search) for any news-related query."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "News topic or 'top news today' for general headlines",
                }
            },
            "required": ["query"],
        },
    },
    
    
    
    
    {
        "name": "get_weather",
        "description": (
            "Get current local weather conditions (temperature, humidity, wind, sky). "
            "Call when the user asks about the weather or outdoor conditions."
        ),
        "input_schema": {
            "type": "object",
            "properties": {},
            "required": [],
        },
    },
    {
        "name": "set_volume",
        "description": (
            "Adjust the physical speaker volume level (0-100% or relative shift). "
            "ALWAYS call this tool whenever the user asks to change, set, raise, or lower the volume "
            "(e.g. 'set volume to 70', 'volume 65', 'louder', 'softer', 'set volume to 80%'). "
            "Pass '+15' to raise volume, '-15' to lower it, or an absolute string number like '65' or '70' to set it directly."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "level": {
                    "type": "string",
                    "description": "'+15' raise 15%, '-15' lower 15%, or '70' for absolute 70%",
                }
            },
            "required": ["level"],
        },
    },
    {
        "name": "bluetooth_scan",
        "description": (
            "Scan for nearby Bluetooth speakers. Call this when the user asks to connect to a "
            "Bluetooth speaker or find Bluetooth devices. Takes 8-10 seconds to complete. "
            "Returns a numbered list of discovered devices."
        ),
        "input_schema": {
            "type": "object",
            "properties": {},
            "required": [],
        },
    },
    {
        "name": "bluetooth_connect",
        "description": (
            "Connect to a Bluetooth device from the last scan. Pass the device name or number "
            "(e.g. '1', '2', 'JBL Flip') as the identifier. On success, audio output routes "
            "through the Bluetooth speaker automatically."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "identifier": {
                    "type": "string",
                    "description": "Device name or number from the last scan (e.g. '1', 'second', 'JBL Flip 6')",
                }
            },
            "required": ["identifier"],
        },
    },
    {
        "name": "bluetooth_disconnect",
        "description": (
            "Disconnect from a connected Bluetooth speaker or device, or disconnect all. "
            "Call when the user asks to disconnect from Bluetooth, stop playing on the Bluetooth speaker, "
            "or unpair/disconnect from a speaker."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "identifier": {
                    "type": "string",
                    "description": "Optional device name, number, or 'all' to disconnect all Bluetooth devices",
                }
            },
            "required": [],
        },
    },
    {
        "name": "set_voice_output",
        "description": (
            f"Switch {config.SKULL_NAME}'s vocal output destination between its own internal speaker "
            "and a connected Bluetooth speaker. Call when the user asks to 'speak through the Bluetooth speaker', "
            "'switch voice to Bluetooth', 'return voice to internal speaker', 'speak on your own speaker', etc."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "target": {
                    "type": "string",
                    "enum": ["internal", "bluetooth"],
                    "description": f"'internal' to speak on {config.SKULL_NAME}'s own speaker, 'bluetooth' to speak on the Bluetooth speaker",
                }
            },
            "required": ["target"],
        },
    },
    {
        "name": "get_distance",
        "description": (
            "Measure the exact physical distance to the user or an obstacle using the laser rangefinder "
            "/ Time-of-Flight sensor. Call when the user asks 'how far away am I', 'how far is that object', "
            "'check rangefinder', 'measure distance', 'how close am I', or asks about distance/range."
        ),
        "input_schema": {
            "type": "object",
            "properties": {},
            "required": [],
        },
    },
    {
        "name": "get_bambu_status",
        "description": (
            "Retrieve the current status of the Bambu 3D printer, including print state, "
            "percentage complete, remaining time, nozzle/bed temperatures, active errors, "
            "and file name."
        ),
        "input_schema": {
            "type": "object",
            "properties": {},
            "required": [],
        },
    },
    {
        "name": "connect_bambu_printer",
        "description": (
            "Connect to or configure a Bambu 3D printer step-by-step. "
            "Use this tool whenever the user wants to connect to or set up a 3D printer, or provides setup details. "
            "CRITICAL CONVERSATIONAL RULES:\n"
            "1. Ask for credentials ONE AT A TIME in sequential order: IP address FIRST, then Serial Number SECOND, then Access Code THIRD.\n"
            "2. If IP address is missing, prompt ONLY for the IP address.\n"
            "3. If IP address is provided but Serial Number is missing, confirm the IP address and prompt ONLY for the Serial Number.\n"
            "4. If IP & Serial Number are provided but Access Code is missing, confirm the Serial Number and prompt ONLY for the Access Code.\n"
            "5. Never ask for all three at once unless the user stated all three simultaneously."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "ip_address": {
                    "type": "string",
                    "description": "IP address of the 3D printer, e.g. '192.168.0.81'",
                },
                "serial_number": {
                    "type": "string",
                    "description": "Serial number of the 3D printer, e.g. '0938AC5B0600679'",
                },
                "access_code": {
                    "type": "string",
                    "description": "Access code from printer settings e.g. '87c83659'",
                },
            },
            "required": [],
        },
    },
    {
        "name": "set_weather_location",
        "description": (
            "Set or update the user's location for weather forecasts. "
            "Use when the user says 'set weather location to [City]', 'change weather location to [City]', "
            "or 'update my location for weather'. Geocodes city names (e.g. 'Seattle, WA', 'Chicago', 'London') "
            "to latitude and longitude and updates configuration."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "location": {
                    "type": "string",
                    "description": "City name and optional state/country e.g. 'Seattle, WA' or 'Chicago'",
                },
            },
            "required": ["location"],
        },
    },
    {
        "name": "set_display_rotation",
        "description": (
            "Adjust or set the hardware eye display rotation and fine angle offset in degrees. "
            "Use when the user says 'rotate eye 15 degrees clockwise', 'nudge display rotation counter-clockwise', "
            "or 'flip eye display upside down'."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "fine_rotation_delta": {
                    "type": "number",
                    "description": "Degrees to add to or subtract from current fine rotation offset e.g. 15.0 or -10.0",
                },
                "fine_rotation_exact": {
                    "type": "number",
                    "description": "Exact fine rotation angle in degrees e.g. 15.0 or 0.0",
                },
                "rotation_quadrant": {
                    "type": "integer",
                    "description": "Hardware quadrant orientation in degrees e.g. 0, 90, 180, 270",
                },
            },
            "required": [],
        },
    },
    {
        "name": "show_display_alignment",
        "description": (
            "Display an UP alignment arrow (▲) and angle calibration grid on the hardware eye screen. "
            "Use when the user says 'show me up on the display', 'display up arrow', 'show alignment grid', "
            "or wants to see which direction the screen considers UP to calibrate physical rotation."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "duration_seconds": {
                    "type": "number",
                    "description": "Duration in seconds to display the alignment mode e.g. 60.0",
                },
            },
            "required": [],
        },
    },
    {
        "name": "set_audio_sensitivity",
        "description": (
            "Adjust microphone recording sensitivity, noise floor threshold, or silence detection threshold. "
            "Use ONLY when the user asks about microphone recording sensitivity, audio pickup, mic noise floor, or silence threshold "
            "(e.g. 'make microphone more sensitive', 'increase mic noise rejection'). Do NOT use for wake word threshold queries."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "sensitivity_level": {
                    "type": "string",
                    "description": "Predefined sensitivity level e.g. 'high' (more sensitive pickup), 'medium' (standard), 'low' (higher noise rejection)",
                },
                "silence_threshold": {
                    "type": "integer",
                    "description": "Explicit RMS silence threshold e.g. 300 (very sensitive), 500 (normal), 800 (high noise rejection)",
                },
            },
            "required": [],
        },
    },
    {
        "name": "set_wake_word_sensitivity",
        "description": (
            "Adjust wake word detection trigger sensitivity or threshold. "
            "Use ONLY when the user explicitly asks about wake word sensitivity, wake word threshold, trigger sensitivity, "
            "stopping false wake ups, or making the wake word more/less sensitive "
            "(e.g. 'increase wake word sensitivity', 'make wake word less sensitive', 'set wake word threshold to 0.70', 'stop false wake ups')."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "sensitivity_level": {
                    "type": "string",
                    "description": "Predefined wake sensitivity e.g. 'high' or 'more_sensitive' (wakes up easier), 'medium' (standard 0.65), 'low', 'strict', or 'less_sensitive' (reduces false triggers)",
                },
                "wake_word_threshold": {
                    "type": "number",
                    "description": "Explicit wake word sensitivity threshold (0.1 to 0.9) e.g. 0.5 (sensitive / low threshold), 0.75 (strict / high threshold)",
                },
            },
            "required": [],
        },
    },

    {
        "name": "set_cast_target",
        "description": (
            "Set or update the default Google Home / Chromecast audio speaker device target. "
            "Use when the user says 'set default cast speaker to [Device Name]', 'cast to Kitchen speaker', "
            "or 'enable/disable audio casting'."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "device_name": {
                    "type": "string",
                    "description": "Name of the Google Home / Chromecast device e.g. 'Kitchen speaker', 'Living Room speaker'",
                },
                "enabled": {
                    "type": "boolean",
                    "description": "Whether audio casting to Google Home / Chromecast is enabled",
                },
            },
            "required": [],
        },
    },
    {
        "name": "remember_fact",
        "description": (
            "Permanently store a fact the user has explicitly asked to be remembered. "
            "Use when the user says 'remember that...', 'please remember...', 'don't forget that...', etc. "
            "Store the fact exactly as stated. This memory persists forever until the user asks to forget it."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "fact": {
                    "type": "string",
                    "description": "The exact fact to remember, as a clear statement (e.g. 'The user's anniversary is June 12th')",
                }
            },
            "required": ["fact"],
        },
    },
    {
        "name": "forget_fact",
        "description": (
            "Remove a fact the user has explicitly asked to be forgotten. "
            "Use when the user says 'forget that...', 'stop remembering...', 'erase...', etc."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "A word or phrase identifying which fact to remove (e.g. 'address', 'phone number')",
                }
            },
            "required": ["query"],
        },
    },
    {
        "name": "update_fact",
        "description": (
            "Replace an existing long-term memory fact with a corrected version. "
            "Use when the user says 'update my...', 'change my...', 'correct that...', "
            "'my address has changed to...', etc. Finds the old fact by keyword and replaces it."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "Keyword identifying the fact to replace (e.g. 'address', 'phone')",
                },
                "new_fact": {
                    "type": "string",
                    "description": "The corrected fact as a full statement (e.g. 'The user's address is now 500 Oak Street')",
                },
            },
            "required": ["query", "new_fact"],
        },
    },
    {
        "name": "set_reminder",
        "description": (
            "Set a timer or reminder that fires after a delay. Use for 'set a timer for X minutes', "
            "'remind me to do Y in Z minutes', 'wake me up in X hours', etc. "
            "Convert the requested duration to seconds. "
            f"Phrase the message in {config.SKULL_NAME}'s character voice (e.g. "
            f"{config.PERSONALITY.get('timer_completion_message', 'Timer complete.')})."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "message": {
                    "type": "string",
                    "description": f"What {config.SKULL_NAME} will speak aloud when the reminder fires.",
                },
                "delay_seconds": {
                    "type": "integer",
                    "description": "Seconds from now until the reminder fires. Convert minutes/hours accordingly.",
                },
            },
            "required": ["message", "delay_seconds"],
        },
    },
    {
        "name": "list_reminders",
        "description": "List all active timers and reminders with their IDs and time remaining.",
        "input_schema": {"type": "object", "properties": {}, "required": []},
    },
    {
        "name": "cancel_reminder",
        "description": "Cancel an active timer or reminder by its ID.",
        "input_schema": {
            "type": "object",
            "properties": {
                "reminder_id": {
                    "type": "string",
                    "description": "The short ID returned when the reminder was set (e.g. 'a3f8c21b').",
                },
            },
            "required": ["reminder_id"],
        },
    },
    {
        "name": "acknowledge_reminders",
        "description": (
            "Stop all currently repeating timer/reminder alerts. Call this when the user "
            "acknowledges an alert — e.g. 'got it', 'acknowledged', 'stop', 'I heard you', "
            "'silence', 'ok ok', 'enough'. Only clears timers that have already expired and "
            "are repeating; pending future timers are never affected."
        ),
        "input_schema": {"type": "object", "properties": {}, "required": []},
    },
    {
        "name": "set_quiet_mode",
        "description": (
            f"Enable or disable silent mode — whether {config.SKULL_NAME} makes unprompted PERIODIC "
            "(idle) observations on its own while waiting. Set enabled=true when the user "
            "asks for silence, e.g. 'silent mode', 'be quiet', 'stop talking on your own', "
            "'no more observations', 'hold your tongue'. Set enabled=false when the user "
            "lifts it, e.g. 'you may speak', 'resume observations', 'you can talk again', "
            f"'end silent mode'. This does NOT mute replies to direct questions — {config.SKULL_NAME} "
            "still answers when addressed; it only governs self-initiated idle remarks."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "enabled": {
                    "type": "boolean",
                    "description": "true to enter silent mode (no idle observations); false to resume them.",
                },
            },
            "required": ["enabled"],
        },
    },
    {
        "name": "set_sleep_schedule",
        "description": (
            f"Set or adjust {config.SKULL_NAME}'s quiet hours / sleep schedule. During sleep hours, "
            f"{config.SKULL_NAME} is completely silent (no unprompted observations or morning greetings). "
            "Use when the user asks to adjust sleep hours, quiet hours, or night mode (e.g., "
            "'set your sleep schedule from 11 PM to 7 AM', 'change quiet hours to midnight until 8am', "
            "'your sleep hours are 0 to 7'). Hours must be in 24-hour format (0 = Midnight, 23 = 11 PM)."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "start_hour": {
                    "type": "integer",
                    "description": "Start hour of sleep schedule in 24-hour format (0–23, e.g. 0 for Midnight, 23 for 11 PM).",
                },
                "end_hour": {
                    "type": "integer",
                    "description": "End hour of sleep schedule in 24-hour format (0–23, e.g. 7 for 7 AM, 8 for 8 AM).",
                },
                "enabled": {
                    "type": "boolean",
                    "description": "true to enable the sleep schedule (default true).",
                },
            },
            "required": ["start_hour", "end_hour"],
        },
    },
    


    {
        "name": "shift_mood",
        "description": (
            f"Update {config.SKULL_NAME}'s current personality disposition. Call this OCCASIONALLY — "
            "only when the conversation strongly warrants a shift. Examples: a discussion "
            "of Chaos threats → SUSPICIOUS or VIGILANT; ancient history or lore → "
            "CONTEMPLATIVE; dark or tragic news → MELANCHOLIC; completing a task well → "
            "DUTIFUL; Imperial devotion or praise → FERVENT. Do not call this every turn. "
            "Mood should shift rarely and feel earned."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "mood": {
                    "type": "string",
                    "enum": ["VIGILANT", "CONTEMPLATIVE", "SUSPICIOUS", "DUTIFUL", "MELANCHOLIC", "FERVENT"],
                    "description": "The new personality disposition.",
                },
            },
            "required": ["mood"],
        },
    },
    
    
    {
        "name": "auspex_scan",
        "description": (
            "Scan the skull's internal cogitator systems (SoC temperature, memory/RAM usage, "
            "disk storage, CPU load, and network/noosphere latency). Returns a detailed "
            "status report of all hardware parameters."
        ),
        "input_schema": {
            "type": "object",
            "properties": {},
            "required": [],
        },
    },
    
    
    
    
    {
        "name": "set_spotify_volume",
        "description": "Set the volume of Spotify Connect playback as a percentage (0-100).",
        "input_schema": {
            "type": "object",
            "properties": {
                "level": {
                    "type": "integer",
                    "minimum": 0,
                    "maximum": 100,
                    "description": "Volume percentage level (0-100)."
                }
            },
            "required": ["level"]
        }
    },
    {
        "name": "adjust_spotify_volume",
        "description": "Increase or decrease Spotify Connect volume level by a relative percentage (e.g. +10 or -15).",
        "input_schema": {
            "type": "object",
            "properties": {
                "change": {
                    "type": "integer",
                    "description": "Relative volume adjustment percentage."
                }
            },
            "required": ["change"]
        }
    },
    {
        "name": "get_spotify_current_track",
        "description": (
            "Check what song, artist, album, or track is currently playing on Spotify on any connected device. "
            "Use when the user asks 'what song is playing?', 'what's playing on Spotify right now?', 'who sings this?', etc."
        ),
        "input_schema": {
            "type": "object",
            "properties": {},
            "required": []
        }
    },
    {
        "name": "refresh_voice_cache",
        "description": "Refresh, clear, or rebuild pre-compiled cached ElevenLabs voice files and phrases. Use when user says 'refresh voice', 'clear voice cache', etc.",
        "input_schema": {
            "type": "object",
            "properties": {}
        }
    },
    {
        "name": "rebuild_sounds",
        "description": "Clear and rebuild all spoken voice phrases (boot phrase, wake phrases, cogitating phrases) using the active ElevenLabs voice. Sound effects remain unchanged. Use when user says 'rebuild sounds', 'rebuild your sounds', 'rebuild voice phrases', 'regenerate speech phrases', etc.",
        "input_schema": {
            "type": "object",
            "properties": {}
        }
    },
    {
        "name": "self_update",
        "description": "Trigger a self-update by pulling the latest code from GitHub, installing new dependencies, and restarting the service.",
        "input_schema": {
            "type": "object",
            "properties": {}
        }
    },
    {
        "name": "set_honorific",
        "description": "Set or change the user's preferred honorific or title (e.g. 'Master', 'Mistress', 'Lord', 'Captain', 'Doctor', 'Magos'). Use when the user says 'change my honorific to...', 'set my title to...', 'call me...', 'address me as...', etc.",
        "input_schema": {
            "type": "object",
            "properties": {
                "honorific": {
                    "type": "string",
                    "description": "The new preferred honorific or title (e.g. 'Master', 'Mistress', 'Lord', 'Captain', 'Doctor', 'Magos')."
                }
            },
            "required": ["honorific"]
        }
    },
    {
        "name": "reboot_system",
        "description": "Reboot and restart the physical Host operating system (the Raspberry Pi hardware). Call when the user says 'reboot', 'restart', 'reboot system', etc.",
        "input_schema": {
            "type": "object",
            "properties": {}
        }
    },
    {
        "name": "shutdown_system",
        "description": "Shutdown and power off the physical Host operating system (the Raspberry Pi hardware). Call when the user says 'shutdown', 'shut down', 'power off', 'turn off', etc.",
        "input_schema": {
            "type": "object",
            "properties": {}
        }
    },
    {
        "name": "switch_personality",
        "description": (
            "Switch the active AI personality on this device. Use when the user asks to switch to, "
            "activate, or talk to another personality. The switch persists through reboots. "
            "The current assistant will say a goodbye and then hand off to the requested personality."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "personality": {
                    "type": "string",
                    "enum": list(json.loads((pathlib.Path(__file__).parent.parent / "personalities" / "personalities.json").read_text())["personalities"].keys()),
                    "description": "Which personality to switch to."
                }
            },
            "required": ["personality"]
        }
    },
    {
        "name": "rotate_display",
        "description": "Adjust or set the fine rotation offset of the eye display screen in degrees.",
        "input_schema": {
            "type": "object",
            "properties": {
                "degrees": {
                    "type": "number",
                    "description": "Degrees to rotate. Positive numbers rotate clockwise / right, negative numbers rotate counter-clockwise / left."
                },
                "mode": {
                    "type": "string",
                    "enum": ["relative", "absolute"],
                    "description": "Whether to rotate relative to current position (default: relative) or set an absolute angle (absolute)."
                }
            },
            "required": ["degrees"]
        }
    },
    {
        "name": "set_voice_wait_duration",
        "description": (
            "Adjust the listening silence delay or voice wait duration (in seconds) that the system waits "
            "during recording after the user stops speaking before it finishes recording. "
            "Use when the user asks to 'change listening silence delay', 'set silence delay to 4 seconds', "
            "'wait longer when I pause speaking', 'give me 5 seconds of silence', 'increase voice wait duration', etc."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "seconds": {
                    "type": "number",
                    "description": "Number of seconds of silence to wait before ending recording (e.g. 1.5, 2.0, 3.5, 5.0)",
                }
            },
            "required": ["seconds"]
        }
    },
    {
        "name": "cancel_printer_alerts",
        "description": "Cancel and stop any repeating verbal alerts/notifications about the 3D printer status (such as completion alerts or health errors).",
        "input_schema": {
            "type": "object",
            "properties": {}
        }
    },
    {
        "name": "display_art",
        "description": "Search the web for Warhammer 40k or Necromunda artwork matching the query, download it, and project/display it on the skull's eye display screen.",
        "input_schema": {
            "type": "object",
            "properties": {
                "search_query": {
                    "type": "string",
                    "description": "Specific search query for the artwork, e.g. 'Space Marine', 'Sister of Battle', 'Necromunda Escher gang'."
                }
            },
            "required": ["search_query"]
        }
    },
    {
        "name": "capture_and_describe_surroundings",
        "description": "Capture a live image from the physical camera sensor on demand and use the Vision LLM to analyze and describe what is currently in front of the skull.",
        "input_schema": {
            "type": "object",
            "properties": {}
        }
    },
    {
        "name": "register_face",
        "description": "Capture a series of facial images over 5 seconds to train or update the local face recognition database for a specific user.",
        "input_schema": {
            "type": "object",
            "properties": {
                "name": {
                    "type": "string",
                    "description": "Name of the person being registered (e.g. 'Sean', 'Sarah')."
                }
            },
            "required": ["name"]
        }
    },
    {
        "name": "register_voice",
        "description": "Enrolls a speaker's voice in the local speaker identification database. Records 3 voice samples after verbal prompt chimes.",
        "input_schema": {
            "type": "object",
            "properties": {
                "name": {
                    "type": "string",
                    "description": "Name of the person registering their voice (e.g. 'Sean', 'Alex')."
                }
            },
            "required": ["name"]
        }
    },
    {
        "name": "play_idle_animation",
        "description": f"Trigger an idle/screensaver animation on the eye display immediately for a specified duration. Available animations: {_saver_desc}.",
        "input_schema": {
            "type": "object",
            "properties": {
                "animation_name": {
                    "type": "string",
                    "description": "Specific screensaver animation to play. If omitted, selects one randomly.",
                    "enum": _screensaver_names,
                },
                "duration_seconds": {
                    "type": "number",
                    "description": "Duration to run the animation in seconds (default: 60)."
                }
            }
        }
    },
    {
        "name": "get_daily_briefing",
        "description": "Compile and deliver the daily morning briefing (weather, news, hive telemetry) for the master.",
        "input_schema": {
            "type": "object",
            "properties": {}
        }
    },
    {
        "name": "purge_identity",
        "description": "Purge all biometric data (visage/face training, voice profiles) and memory records associated with a specific person's name.",
        "input_schema": {
            "type": "object",
            "properties": {
                "name": {
                    "type": "string",
                    "description": "Name of the person to purge (e.g. 'Tara')."
                }
            },
            "required": ["name"]
        }
    },
    ]
    base_tools.extend(wfrp.tools.TOOLS)
    if _brain_module and hasattr(_brain_module, 'get_tools'):
        base_tools.extend(_brain_module.get_tools())
    return base_tools
