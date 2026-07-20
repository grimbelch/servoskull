from __future__ import annotations
import json
import pathlib
import re
import subprocess
import sys
from datetime import datetime
from skull import config
from skull.config import SYSTEM_PROMPT
from skull import search as _search
from skull import memory as _memory
from skull import reminders as _reminders
from skull import mood as _mood
from skull import quiet as _quiet
from skull import candles as _candles
from skull import llm as _llm
from skull import display as _display

_history: list[dict] = []

# Tools that hit the network/hardware and can take a noticeable moment. Omega-7
# speaks a short "stand by" before running any of these so the user gets feedback.
_SLOW_TOOLS = {"web_search", "news_search", "necromunda_rules", "warhammer40k_rules", "netepic_rules", "netea_rules", "get_weather", "bluetooth_scan", "auspex_scan", "display_art", "capture_and_describe_surroundings", "register_face", "register_voice"}
_HISTORY_PATH = config.data_path(config.HISTORY_FILE)
_last_turn_tools: list[str] = []


def last_turn_tools() -> list[str]:
    return _last_turn_tools


def _save_history() -> None:
    try:
        _HISTORY_PATH.parent.mkdir(parents=True, exist_ok=True)
        with _HISTORY_PATH.open("w") as f:
            json.dump(_history, f)
    except Exception as e:
        print(f"[brain] History save error: {e}")


def _load_history() -> None:
    global _history
    try:
        if _HISTORY_PATH.exists():
            with _HISTORY_PATH.open() as f:
                _history = json.load(f)
            print(f"[brain] Restored {len(_history) // 2} conversation turns from history")
    except Exception:
        pass


_load_history()

def _build_tools() -> list[dict]:
    """Build the Anthropic tool-use schema at startup, pulling the screensaver
    list dynamically from display.py so future additions there are reflected
    here automatically without any edits to brain.py."""
    _screensaver_names = _display.get_screensaver_names()
    _saver_desc = ", ".join(f"'{n}'" for n in _screensaver_names)
    return [
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
        "name": "necromunda_rules",
        "description": (
            "Look up Necromunda tabletop game rules from the local offline rules library (Rules as Written). "
            "Use for any question about Necromunda mechanics, gangs, weapons, skills, "
            "injuries, campaigns, scenarios, or equipment — including the Trading Post and "
            "Black Market: item availability, rarity, cost, exclusive/illegal items, and "
            "special ammunition. Always use this tool before answering a Necromunda rules "
            "question rather than relying on memory."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "Rule, mechanic, or topic to look up (e.g. 'fighter activation', 'injury roll', 'House Goliath gang list')",
                }
            },
            "required": ["query"],
        },
    },
    {
        "name": "warhammer40k_rules",
        "description": (
            "Look up Warhammer 40,000 (11th edition) tabletop rules from the local rules "
            "library — the core rules, faction packs (detachments, datasheets, stratagems, "
            "enhancements, wargear, unit stats), rules updates/FAQs, and event companions. "
            "Use for any 40k question: army rules, a specific unit's profile or abilities, "
            "weapon stats, stratagems, detachment rules, points, or matched-play/tournament "
            "rules. Always use this tool before answering a 40k rules question rather than "
            "relying on memory."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "Unit, rule, weapon, stratagem, or topic to look up (e.g. 'Defiler stats', 'World Eaters Brazen Engines detachment', 'Blessings of Khorne', 'Lone Operative')",
                }
            },
            "required": ["query"],
        },
    },
    {
        "name": "netepic_rules",
        "description": (
            "Look up NetEpic (also called Epic 2nd Edition) tabletop game rules from the local "
            "offline rules library — the NetEpic 5.0 core rules, optional rules, and army books "
            "(Adeptus Astartes/Space Marines, Adeptus Mechanicus, Adeptus Militaris/Imperial Guard, "
            "Adeptus Ministorum, Chaos, Tyranid, Squat, Ork, Slann, Tau). Use for any NetEpic "
            "question: game phases, movement, combat, unit stats and army cards, formations, "
            "titans, weapons, points, or army list building. This is a DIFFERENT game from Net "
            "Epic Armageddon / NetEA (use netea_rules for that) — disambiguate by the keywords "
            "'2nd edition' (NetEpic) versus 'Armageddon' or '3rd edition' (NetEA). Always use this "
            "tool before answering a NetEpic / Epic 2nd Edition question rather than relying on memory."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "Rule, unit, army card, weapon, or topic to look up (e.g. 'orders phase', 'Space Marine Tactical Company', 'Warlord Titan', 'close combat resolution', 'Ork Gargant')",
                }
            },
            "required": ["query"],
        },
    },
    {
        "name": "netea_rules",
        "description": (
            "Look up Net Epic Armageddon (NetEA — also called 'Armageddon' or 'Epic 3rd Edition') "
            "tabletop game rules from the local offline rules library: the NetEA rules, tournament "
            "pack, FAQ, and army lists (Space Marines, Chaos, Eldar, Dark Eldar, Imperial Guard, "
            "Adeptus Mechanicus, Orks, Necrons, Tyranids, Tau, Squats, Inquisition, and their many "
            "sub-factions). Use for any NetEA question: mechanics, blast markers, army lists, "
            "formations, units, special rules, or tournament regulations. This is a DIFFERENT game "
            "from NetEpic / Epic 2nd Edition (use netepic_rules for that) — disambiguate by the "
            "keywords 'Armageddon' or '3rd edition' (NetEA) versus '2nd edition' (NetEpic). Always "
            "use this tool before answering a NetEA question rather than relying on memory."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "Rule, unit, formation, or topic to look up (e.g. 'blast markers', 'Space Marine Tactical formation', 'aerospace operations', 'Ork Gargant Mob army list')",
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
            "Adjust the speaker volume. Pass '+15' to raise by 15%, '-15' to lower by 15%, "
            "or '80' to set an absolute level. Call when user says louder, quieter, volume up/down, etc."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "level": {
                    "type": "string",
                    "description": "'+15' raise 15%, '-15' lower 15%, or '80' for absolute 80%",
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
            f"Phrase the message in {config.SKULL_NAME}'s 40k voice (e.g. 'Your 5-minute cogitation cycle is complete.' "
            "or 'Reminder, my lord: the dog requires its evening patrol.')."
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
        "name": "set_candles",
        "description": (
            f"Light or extinguish the flickering candles atop {config.SKULL_NAME}. "
            "Set lit=true when the user says 'light the candles', 'candles on', "
            "'ignite the candles'. Set lit=false when the user says 'dim the candles', "
            "'douse the candles', 'put out the candles', 'candles off', 'extinguish the "
            "candles'. The candles are either fully lit or fully out — they cannot be "
            "partially dimmed, so treat 'dim' as 'extinguish'."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "lit": {
                    "type": "boolean",
                    "description": "true to light the candles; false to extinguish them.",
                },
            },
            "required": ["lit"],
        },
    },
    {
        "name": "roll_dice",
        "description": (
            "Simulate dice rolls for Warhammer 40k or Necromunda attacks. "
            "Runs the complete roll sequence (hits, wounds, saves, and optionally Feel No Pain) "
            "and returns a detailed step-by-step result including rerolls."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "num_dice": {
                    "type": "integer",
                    "description": "The number of attacks/dice to roll initially.",
                },
                "hit_on": {
                    "type": "integer",
                    "minimum": 2,
                    "maximum": 6,
                    "description": "The target roll required to hit (e.g. 3 for 3+).",
                },
                "wound_on": {
                    "type": "integer",
                    "minimum": 2,
                    "maximum": 6,
                    "description": "The target roll required to wound (e.g. 4 for 4+).",
                },
                "save_on": {
                    "type": "integer",
                    "minimum": 2,
                    "maximum": 6,
                    "description": "Optional: Base armour save of the target (e.g. 3 for 3+). If omitted, saves are not rolled.",
                },
                "ap": {
                    "type": "integer",
                    "description": "Optional: Armour penetration value (e.g. 2 or -2). Will be added to the required save roll.",
                },
                "invul_save": {
                    "type": "integer",
                    "minimum": 2,
                    "maximum": 6,
                    "description": "Optional: Target's invulnerable save (e.g. 4 for 4++). Will cap the save required.",
                },
                "reroll_hits": {
                    "type": "string",
                    "enum": ["none", "ones", "failed"],
                    "description": "Optional: Reroll rules for hits. Defaults to 'none'.",
                },
                "reroll_wounds": {
                    "type": "string",
                    "enum": ["none", "ones", "failed"],
                    "description": "Optional: Reroll rules for wounds. Defaults to 'none'.",
                },
                "feel_no_pain": {
                    "type": "integer",
                    "minimum": 2,
                    "maximum": 6,
                    "description": "Optional: Feel No Pain value (e.g. 5 for 5+++). Will roll for unsaved wounds.",
                },
            },
            "required": ["num_dice", "hit_on", "wound_on"],
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
        "name": "set_active_game",
        "description": "Configure which tabletop game is currently being played (e.g. 'Warhammer 40k', 'Necromunda', 'NetEpic', or 'NetEpic Armageddon') so that dice rolls default to that game context.",
        "input_schema": {
            "type": "object",
            "properties": {
                "game": {
                    "type": "string",
                    "enum": ["Warhammer 40k", "Necromunda", "NetEpic", "NetEpic Armageddon"],
                    "description": "The name of the game being played."
                }
            },
            "required": ["game"]
        }
    },
    {
        "name": "roll_necromunda_dice",
        "description": "Roll specialized Necromunda dice (Firepower/Ammo checks, Injury dice, Scatter dice, Location dice, or standard D6 checks).",
        "input_schema": {
            "type": "object",
            "properties": {
                "dice_type": {
                    "type": "string",
                    "enum": ["firepower", "injury", "scatter", "location", "d6"],
                    "description": "The type of specialized Necromunda die to roll."
                },
                "count": {
                    "type": "integer",
                    "minimum": 1,
                    "description": "The number of dice to roll."
                },
                "target": {
                    "type": "integer",
                    "minimum": 1,
                    "maximum": 6,
                    "description": "Optional: For D6 checks, the target number required (e.g. 4 for 4+)."
                }
            },
            "required": ["dice_type"]
        }
    },
    {
        "name": "roll_standard_dice",
        "description": "Roll standard multi-sided dice (e.g. D6, D10, D20, D100) and return the individual results and sum.",
        "input_schema": {
            "type": "object",
            "properties": {
                "count": {
                    "type": "integer",
                    "minimum": 1,
                    "description": "The number of dice to roll."
                },
                "sides": {
                    "type": "integer",
                    "minimum": 2,
                    "description": "The number of sides per die (e.g. 6 for D6, 20 for D20)."
                },
                "target": {
                    "type": "integer",
                    "minimum": 1,
                    "description": "Optional: target number to succeed (e.g. roll >= target)."
                }
            },
            "required": ["count", "sides"]
        }
    },
    {
        "name": "roll_epic_dice",
        "description": "Roll dice for NetEpic (2nd edition) or NetEpic Armageddon (NetEA/3rd edition) shooting or close combat/assault resolution.",
        "input_schema": {
            "type": "object",
            "properties": {
                "system": {
                    "type": "string",
                    "enum": ["NetEpic", "NetEA"],
                    "description": "Optional: The Epic rules system to use. Defaults to the active game if not specified."
                },
                "roll_type": {
                    "type": "string",
                    "enum": ["shooting", "combat_resolution", "save", "morale"],
                    "description": "The type of roll: shooting attacks, close combat/assault resolution, armor saves, or morale tests."
                },
                "count": {
                    "type": "integer",
                    "minimum": 1,
                    "description": "The number of dice to roll."
                },
                "to_hit": {
                    "type": "integer",
                    "minimum": 2,
                    "maximum": 6,
                    "description": "Optional: The target number required to hit (e.g. 4 for 4+)."
                },
                "save_on": {
                    "type": "integer",
                    "minimum": 1,
                    "maximum": 6,
                    "description": "Optional: The required save value (e.g. 5 for 5+)."
                },
                "tsm": {
                    "type": "integer",
                    "description": "Optional (NetEpic only): Target Save Modifier (negative value, e.g. -2). Modifies the save roll."
                },
                "macro_weapon": {
                    "type": "boolean",
                    "description": "Optional (NetEA only): If true, the attack is from a macro-weapon (MW), negating standard and cover saves."
                },
                "reinforced_armour": {
                    "type": "boolean",
                    "description": "Optional (NetEA only): If true, the target has reinforced armour (allows save reroll against non-macro hits, or normal save against macro hits)."
                },
                "caf": {
                    "type": "integer",
                    "description": "Optional (NetEpic close combat only): Close Assault Factor of the combatant."
                },
                "opponent_caf": {
                    "type": "integer",
                    "description": "Optional (NetEpic close combat only): Close Assault Factor of the opponent."
                },
                "opponent_count": {
                    "type": "integer",
                    "minimum": 1,
                    "description": "Optional: For NetEpic close combat or NetEA assaults, the number of dice rolled by the opponent."
                },
                "morales": {
                    "type": "integer",
                    "minimum": 1,
                    "maximum": 6,
                    "description": "Optional (Morale test only): Morale threshold required."
                }
            },
            "required": ["roll_type", "count"]
        }
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
        "name": "refresh_voice_cache",
        "description": "Refresh the pre-compiled and cached ElevenLabs voice files by clearing the cache and regenerating them in the background.",
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
        "name": "reboot_system",
        "description": "Reboot the physical Host operating system (the Raspberry Pi hardware).",
        "input_schema": {
            "type": "object",
            "properties": {}
        }
    },
    {
        "name": "shutdown_system",
        "description": "Shutdown and power off the physical Host operating system (the Raspberry Pi hardware).",
        "input_schema": {
            "type": "object",
            "properties": {}
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
    }
]


_TOOLS = _build_tools()

_ORDINALS = {
    "first": 0, "1": 0,
    "second": 1, "2": 1,
    "third": 2, "3": 2,
    "fourth": 3, "4": 3,
    "fifth": 4, "5": 4,
}


def _resolve_bt_device(identifier: str, devices: list[dict]) -> dict | None:
    s = identifier.lower().strip()
    if s in _ORDINALS:
        i = _ORDINALS[s]
        return devices[i] if i < len(devices) else None
    try:
        i = int(s) - 1
        return devices[i] if 0 <= i < len(devices) else None
    except ValueError:
        pass
    for d in devices:
        if s in d["name"].lower():
            return d
    return None


_SPOTIFY_RE = re.compile(
    r"\[SPOTIFY(?::([^\]|]+?)(?:\s*\|\s*on:\s*([^\]]+))?)?\]|\[SPOTIFY_(PAUSE|RESUME|SKIP)\]"
)

# Deterministic silent-mode intent. haiku often acknowledges a silence/resume
# request verbally without actually calling set_quiet_mode, so respond() uses
# these as a fallback to reconcile the state when the tool wasn't invoked.
_QUIET_OFF_RE = re.compile(
    r"\byou (?:may|can) (?:speak|talk)\b|\b(?:speak|talk) (?:again|freely)\b"
    r"|\bresume (?:your )?(?:observ|chatter|remarks?|speech|commentary)"
    r"|\bend (?:silent|quiet) mode\b|\bstop being (?:silent|quiet)\b"
    r"|\bbreak your silence\b|\byou(?:'re| are) allowed to (?:talk|speak)\b"
    r"|\byou may resume\b|\bstart talking again\b",
    re.I,
)
_QUIET_ON_RE = re.compile(
    r"\b(?:be|stay|keep|remain) (?:silent|quiet)\b|\b(?:silent|quiet) mode\b"
    r"|\bhold your tongue\b|\bhush\b|\bshush\b|\bshut up\b|\bpipe down\b|\bzip it\b"
    r"|\bstop (?:your )?(?:observ|talking|chatter|comment)|\bno more (?:observ|comment|chatter|remarks?)"
    r"|\bcease (?:your )?(?:observ|chatter|comment)|\bsilence\b",
    re.I,
)


def _quiet_intent(text: str) -> bool | None:
    """Classify an explicit silence command: True=enter silent mode,
    False=resume, None=no clear command. Resume is checked first so phrases like
    'stop being silent' aren't misread as a request for silence."""
    if _QUIET_OFF_RE.search(text):
        return False
    if _QUIET_ON_RE.search(text):
        return True
    return None


def _strip_actions(text: str) -> str:
    text = re.sub(r"\*[^*]*\*", "", text)
    text = re.sub(r"_[^_]*_", "", text)
    return " ".join(text.split())


def _run_auspex_scan() -> str:
    # 1. Temperature
    from skull.temperature import read_temp_c
    temp = read_temp_c()

    # 2. CPU load
    import os
    import sys
    cpu_count = os.cpu_count() or 1
    cpu_load_pct = 0.0
    try:
        load = os.getloadavg()
        cpu_load_pct = (load[0] / cpu_count) * 100
    except Exception:
        pass

    # 3. Memory
    mem_total_gb, mem_used_gb, mem_pct = 0.0, 0.0, 0.0
    try:
        if sys.platform != "darwin" and os.path.exists("/proc/meminfo"):
            mem_total, mem_avail = 0, 0
            with open("/proc/meminfo") as f:
                for line in f:
                    if line.startswith("MemTotal:"):
                        mem_total = int(line.split()[1]) * 1024
                    elif line.startswith("MemAvailable:"):
                        mem_avail = int(line.split()[1]) * 1024
            if mem_total > 0:
                mem_used = mem_total - mem_avail
                mem_total_gb = mem_total / (1024**3)
                mem_used_gb = mem_used / (1024**3)
                mem_pct = (mem_used / mem_total) * 100
        else:
            import subprocess
            out = subprocess.run(["sysctl", "-n", "hw.memsize"], capture_output=True, text=True, timeout=1).stdout.strip()
            mem_total = int(out)
            vm = subprocess.run(["vm_stat"], capture_output=True, text=True, timeout=1).stdout
            pages_free = 0
            pages_speculative = 0
            pages_purgeable = 0
            page_size = 4096
            for line in vm.splitlines():
                if "Pages free:" in line:
                    pages_free = int(line.split()[-1].strip("."))
                elif "Pages speculative:" in line:
                    pages_speculative = int(line.split()[-1].strip("."))
                elif "Pages purgeable:" in line:
                    pages_purgeable = int(line.split()[-1].strip("."))
                elif "page size of" in line:
                    match_size = re.search(r"page size of (\d+) bytes", line)
                    if match_size:
                        page_size = int(match_size.group(1))
            mem_avail = (pages_free + pages_speculative + pages_purgeable) * page_size
            mem_used = mem_total - mem_avail
            mem_total_gb = mem_total / (1024**3)
            mem_used_gb = mem_used / (1024**3)
            mem_pct = (mem_used / mem_total) * 100
    except Exception:
        mem_total_gb = 4.0
        mem_pct = 25.0
        mem_used_gb = 1.0

    # 4. Disk Usage
    import shutil
    disk_total_gb, disk_used_gb, disk_pct = 0.0, 0.0, 0.0
    try:
        total, used, free = shutil.disk_usage("/")
        disk_total_gb = total / (1024**3)
        disk_used_gb = used / (1024**3)
        disk_pct = (used / total) * 100
    except Exception:
        pass

    # 5. Network / Noosphere Latency
    import subprocess
    latency_ms = None
    noosphere_status = "unreachable"
    try:
        flag = "-t" if sys.platform == "darwin" else "-W"
        res = subprocess.run(["ping", "-c", "1", flag, "1", "1.1.1.1"], capture_output=True, text=True, timeout=1.5)
        if res.returncode == 0:
            match = re.search(r"time=([\d.]+)\s*ms", res.stdout)
            if match:
                latency_ms = float(match.group(1))
                noosphere_status = "connected"
    except Exception:
        pass

    # Compose reports
    report = []
    report.append("--- Noosphere Auspex Diagnostic Report ---")
    if temp is not None:
        report.append(f"Cognitive core temperature: {temp:.1f}°C")
    else:
        report.append("Cognitive core temperature: Sensor offline / Virtual environment emulation")

    report.append(f"Logic-engine (CPU) load: {cpu_load_pct:.1f}% ({cpu_count} active cores)")
    report.append(f"Memory-coils (RAM): {mem_used_gb:.2f} GB / {mem_total_gb:.2f} GB ({mem_pct:.1f}% allocated)")
    report.append(f"Data-vaults (Disk): {disk_used_gb:.1f} GB / {disk_total_gb:.1f} GB ({disk_pct:.1f}% capacity)")

    if noosphere_status == "connected" and latency_ms is not None:
        report.append(f"Noosphere link status: Stable (latency: {latency_ms:.1f} ms)")
    else:
        report.append("Noosphere link status: Disconnected / Offline")

    report.append("System status: Sanctified by the Machine God.")
    report.append("------------------------------------------")
    return "\n".join(report)


def _simulate_dice(
    num_dice: int,
    hit_on: int,
    wound_on: int,
    save_on: int | None = None,
    ap: int = 0,
    invul_save: int | None = None,
    reroll_hits: str = "none",
    reroll_wounds: str = "none",
    feel_no_pain: int | None = None,
) -> str:
    import random
    global _last_roll_result
    display_val = 0

    details = []

    def roll_d6(n: int) -> list[int]:
        return [random.randint(1, 6) for _ in range(n)]

    # Hits
    hit_rolls = roll_d6(num_dice)
    initial_hits = sum(1 for r in hit_rolls if r >= hit_on)

    rerolled_hits_count = 0
    new_hits = 0
    if reroll_hits == "ones":
        ones = sum(1 for r in hit_rolls if r == 1)
        if ones > 0:
            reroll_rolls = roll_d6(ones)
            rerolled_hits_count = ones
            new_hits = sum(1 for r in reroll_rolls if r >= hit_on)
    elif reroll_hits == "failed":
        failed = sum(1 for r in hit_rolls if r < hit_on)
        if failed > 0:
            reroll_rolls = roll_d6(failed)
            rerolled_hits_count = failed
            new_hits = sum(1 for r in reroll_rolls if r >= hit_on)

    total_hits = initial_hits + new_hits

    hit_msg = f"Hit roll: {num_dice} dice needing {hit_on}+ -> {initial_hits} initial hits."
    if reroll_hits != "none" and rerolled_hits_count > 0:
        hit_msg += f" Rerolled {rerolled_hits_count} {reroll_hits} -> +{new_hits} hits."
    hit_msg += f" Total hits: {total_hits}."
    details.append(hit_msg)

    if total_hits == 0:
        details.append("No hits generated. The attack sequence terminates.")
        _last_roll_result = str(display_val)
        return "\n".join(details)

    # Wounds
    wound_rolls = roll_d6(total_hits)
    initial_wounds = sum(1 for r in wound_rolls if r >= wound_on)

    rerolled_wounds_count = 0
    new_wounds = 0
    if reroll_wounds == "ones":
        ones = sum(1 for r in wound_rolls if r == 1)
        if ones > 0:
            reroll_rolls = roll_d6(ones)
            rerolled_wounds_count = ones
            new_wounds = sum(1 for r in reroll_rolls if r >= wound_on)
    elif reroll_wounds == "failed":
        failed = sum(1 for r in wound_rolls if r < wound_on)
        if failed > 0:
            reroll_rolls = roll_d6(failed)
            rerolled_wounds_count = failed
            new_wounds = sum(1 for r in reroll_rolls if r >= wound_on)

    total_wounds = initial_wounds + new_wounds
    display_val = total_wounds

    wound_msg = f"Wound roll: {total_hits} dice needing {wound_on}+ -> {initial_wounds} initial wounds."
    if reroll_wounds != "none" and rerolled_wounds_count > 0:
        wound_msg += f" Rerolled {rerolled_wounds_count} {reroll_wounds} -> +{new_wounds} wounds."
    wound_msg += f" Total wounds: {total_wounds}."
    details.append(wound_msg)

    if total_wounds == 0:
        details.append("No wounds generated. The attack sequence terminates.")
        _last_roll_result = str(display_val)
        return "\n".join(details)

    # Saves
    if save_on is None:
        _last_roll_result = str(display_val)
        return "\n".join(details)

    ap_val = abs(ap)
    modified_save = save_on + ap_val

    save_type = "armour"
    final_save = modified_save
    if invul_save is not None:
        if invul_save < modified_save:
            final_save = invul_save
            save_type = "invulnerable"

    save_rolls = roll_d6(total_wounds)

    if final_save > 6:
        passed_saves = 0
    else:
        passed_saves = sum(1 for r in save_rolls if r >= final_save and r != 1)

    failed_saves = total_wounds - passed_saves
    display_val = failed_saves

    save_details_msg = f"using {save_on}+ base save modified by AP {ap_val} to {modified_save}+"
    if invul_save is not None:
        save_details_msg += f" (invul {invul_save}++ available)"

    save_msg = f"Save roll: Target rolled {total_wounds} {save_type} saves needing {final_save}+ ({save_details_msg}) -> {passed_saves} passed, {failed_saves} failed."
    details.append(save_msg)

    if failed_saves == 0:
        details.append("All saves succeeded. No damage inflicted.")
        _last_roll_result = str(display_val)
        return "\n".join(details)

    # Feel No Pain
    if feel_no_pain is not None:
        fnp_rolls = roll_d6(failed_saves)
        passed_fnps = sum(1 for r in fnp_rolls if r >= feel_no_pain)
        final_damage = failed_saves - passed_fnps
        display_val = final_damage

        fnp_msg = f"Feel No Pain: Target rolled {failed_saves} FNP rolls needing {feel_no_pain}+ -> {passed_fnps} ignored, {final_damage} final damage inflicted."
        details.append(fnp_msg)
    else:
        details.append(f"Result: {failed_saves} damage inflicted.")

    _last_roll_result = str(display_val)
    return "\n".join(details)


def get_current_game() -> str:
    path = config.data_path("current_game.json")
    if not path.exists():
        return "Warhammer 40k"
    try:
        return json.loads(path.read_text()).get("game", "Warhammer 40k")
    except Exception:
        return "Warhammer 40k"


def set_current_game(game: str) -> None:
    path = config.data_path("current_game.json")
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps({"game": game}))
    except Exception as e:
        print(f"[brain] Error saving current game: {e}")


_last_roll_result = "0"


def _trigger_dice_effects(display_val: int | str | None = None) -> None:
    global _last_roll_result
    try:
        from skull import sfx as _sfx
        _sfx.play("dice_roll")
    except Exception as e:
        print(f"[brain] SFX play failed: {e}")

    try:
        val = display_val if display_val is not None else _last_roll_result
        from skull import display as _display
        _display.start_die_roll(val)
    except Exception as e:
        print(f"[brain] Display roll failed: {e}")

    import time as _time
    _time.sleep(1.5)


def _simulate_necromunda(dice_type: str, count: int, target: int | None = None) -> str:
    import random
    global _last_roll_result
    display_val = "0"
    details = []
    
    if dice_type == "firepower":
        total_hits = 0
        ammo_checks = 0
        rolls = []
        for _ in range(count):
            r = random.randint(1, 6)
            if r == 1:
                rolls.append("1 (Ammo Symbol)")
                total_hits += 1
                ammo_checks += 1
            elif r in (2, 3):
                rolls.append("1")
                total_hits += 1
            elif r in (4, 5):
                rolls.append("2")
                total_hits += 2
            else:
                rolls.append("3")
                total_hits += 3
        
        details.append(f"Necromunda Firepower Roll ({count} dice):")
        details.append(f"Individual rolls: {', '.join(rolls)}")
        details.append(f"Total Hits: {total_hits}")
        if ammo_checks > 0:
            details.append(f"WARNING: {ammo_checks} Ammo Check(s) triggered! Weapons may jam or run out of ammunition.")
        else:
            details.append("No Ammo Checks triggered.")
        display_val = str(total_hits)
            
    elif dice_type == "injury":
        flesh = 0
        serious = 0
        out_of_action = 0
        rolls = []
        for _ in range(count):
            r = random.randint(1, 6)
            if r in (1, 2):
                rolls.append("Flesh Wound")
                flesh += 1
            elif r in (3, 4, 5):
                rolls.append("Serious Injury")
                serious += 1
            else:
                rolls.append("Out of Action")
                out_of_action += 1
        
        details.append(f"Necromunda Injury Roll ({count} dice):")
        details.append(f"Individual rolls: {', '.join(rolls)}")
        details.append(f"Summary: {flesh}x Flesh Wound, {serious}x Serious Injury, {out_of_action}x Out of Action")
        
        if count == 1:
            if flesh > 0:
                display_val = "FW"
            elif serious > 0:
                display_val = "SI"
            else:
                display_val = "OA"
        else:
            if out_of_action > 0:
                display_val = "OA"
            elif serious > 0:
                display_val = "SI"
            else:
                display_val = "FW"
        
    elif dice_type == "scatter":
        hits = 0
        arrows = []
        directions = ["North (12 o'clock)", "East (3 o'clock)", "South (6 o'clock)", "West (9 o'clock)"]
        for _ in range(count):
            r = random.randint(1, 6)
            if r in (1, 2):
                arrows.append("Direct Hit")
                hits += 1
            else:
                dir_str = directions[r - 3]
                arrows.append(f"Scatter {dir_str}")
        
        details.append(f"Necromunda Scatter Roll ({count} dice):")
        details.append(f"Individual rolls: {', '.join(arrows)}")
        details.append(f"Summary: {hits}x Direct Hit, {count - hits}x Scatter")
        
        if count == 1:
            if hits > 0:
                display_val = "HIT"
            else:
                dir_word = arrows[0].split()[1].lower()
                if "north" in dir_word:
                    display_val = "N"
                elif "east" in dir_word:
                    display_val = "E"
                elif "south" in dir_word:
                    display_val = "S"
                elif "west" in dir_word:
                    display_val = "W"
                else:
                    display_val = "SC"
        else:
            display_val = str(hits)
        
    elif dice_type == "location":
        locations = ["Head", "Body", "Left Arm", "Right Arm", "Left Leg", "Right Leg"]
        rolls = []
        for _ in range(count):
            r = random.randint(1, 6)
            rolls.append(locations[r - 1])
        
        details.append(f"Necromunda Hit Location Roll ({count} dice):")
        details.append(f"Individual rolls: {', '.join(rolls)}")
        
        if count == 1:
            loc = rolls[0].lower()
            if "head" in loc:
                display_val = "HD"
            elif "body" in loc:
                display_val = "BD"
            elif "left arm" in loc:
                display_val = "LA"
            elif "right arm" in loc:
                display_val = "RA"
            elif "left leg" in loc:
                display_val = "LL"
            elif "right leg" in loc:
                display_val = "RL"
            else:
                display_val = "LOC"
        else:
            display_val = "LOC"
        
    elif dice_type == "d6":
        rolls = [random.randint(1, 6) for _ in range(count)]
        details.append(f"Standard D6 Roll ({count} dice): {', '.join(map(str, rolls))}")
        if target is not None:
            successes = sum(1 for r in rolls if r >= target)
            details.append(f"Successes ({target}+): {successes} passed, {count - successes} failed")
            display_val = str(successes)
        else:
            if count == 1:
                display_val = str(rolls[0])
            else:
                display_val = str(sum(rolls))
            
    _last_roll_result = str(display_val)
    return "\n".join(details)


def _simulate_standard_dice(count: int, sides: int, target: int | None = None) -> str:
    import random
    global _last_roll_result
    display_val = "0"
    rolls = [random.randint(1, sides) for _ in range(count)]
    total = sum(rolls)
    details = [f"Rolled {count}d{sides}: {', '.join(map(str, rolls))} (Total: {total})"]
    if target is not None:
        successes = sum(1 for r in rolls if r >= target)
        details.append(f"Successes ({target}+): {successes} passed, {count - successes} failed")
        display_val = str(successes)
    else:
        if count == 1:
            display_val = str(rolls[0])
        else:
            display_val = str(total)
            
    _last_roll_result = str(display_val)
    return "\n".join(details)


def _simulate_epic_dice(
    system: str,
    roll_type: str,
    count: int,
    to_hit: int | None = None,
    save_on: int | None = None,
    tsm: int = 0,
    macro_weapon: bool = False,
    reinforced_armour: bool = False,
    caf: int = 0,
    opponent_caf: int = 0,
    morales: int | None = None,
    opponent_count: int | None = None,
) -> str:
    import random
    global _last_roll_result
    display_val = "0"
    details = []

    def roll_d6(n: int) -> list[int]:
        return [random.randint(1, 6) for _ in range(n)]

    if roll_type == "shooting":
        rolls = roll_d6(count)
        details.append(f"{system} Shooting Roll ({count} dice): {', '.join(map(str, rolls))}")
        
        hit_count = 0
        hit_rolls = []
        if to_hit is not None:
            for r in rolls:
                if system == "NetEpic" and r == 1:
                    hit_rolls.append(f"{r} (Miss)")
                elif r >= to_hit:
                    hit_rolls.append(f"{r} (Hit)")
                    hit_count += 1
                else:
                    hit_rolls.append(str(r))
            details.append(f"To-Hit rolls: {', '.join(hit_rolls)} -> {hit_count} Hit(s) scored (needing {to_hit}+)")
        else:
            hit_count = count
            details.append(f"Assuming all {count} attack(s) hit.")

        display_val = str(hit_count)

        if hit_count == 0:
            _last_roll_result = str(display_val)
            return "\n".join(details)

        if save_on is not None:
            details.append(f"\nResolving {hit_count} Save(s) (needing {save_on}+):")
            
            if system == "NetEpic":
                save_rolls = roll_d6(hit_count)
                save_results = []
                passed = 0
                for r in save_rolls:
                    mod_roll = r + tsm
                    if mod_roll >= save_on:
                        save_results.append(f"{r} modified to {mod_roll} (Pass)")
                        passed += 1
                    else:
                        save_results.append(f"{r} modified to {mod_roll} (Fail)")
                tsm_str = f" with TSM {tsm}" if tsm != 0 else ""
                details.append(f"Save rolls{tsm_str}: {', '.join(save_results)}")
                details.append(f"Summary: {passed} passed, {hit_count - passed} failed.")
                display_val = str(hit_count - passed)
                
            elif system == "NetEA":
                if macro_weapon:
                    if reinforced_armour:
                        save_rolls = roll_d6(hit_count)
                        passed = sum(1 for r in save_rolls if r >= save_on)
                        details.append(f"Macro-Weapon vs Reinforced Armour (no rerolls allowed): {', '.join(map(str, save_rolls))}")
                        details.append(f"Summary: {passed} passed, {hit_count - passed} failed.")
                        display_val = str(hit_count - passed)
                    else:
                        details.append("Macro-Weapon hits target without Reinforced Armour -> No saves allowed! Target takes full damage.")
                        display_val = str(hit_count)
                else:
                    save_rolls = roll_d6(hit_count)
                    passed = 0
                    failed_rolls = []
                    save_results = []
                    
                    for r in save_rolls:
                        if r >= save_on:
                            save_results.append(f"{r} (Pass)")
                            passed += 1
                        else:
                            save_results.append(f"{r} (Fail)")
                            failed_rolls.append(r)
                            
                    details.append(f"Initial Save rolls: {', '.join(save_results)}")
                    
                    if reinforced_armour and failed_rolls:
                        rerolls = roll_d6(len(failed_rolls))
                        new_passed = sum(1 for r in rerolls if r >= save_on)
                        passed += new_passed
                        reroll_results = [f"{r} (Pass)" if r >= save_on else f"{r} (Fail)" for r in rerolls]
                        details.append(f"Reinforced Armour Rerolls: {', '.join(reroll_results)}")
                    
                    details.append(f"Summary: {passed} passed, {hit_count - passed} failed.")
                    display_val = str(hit_count - passed)

    elif roll_type == "combat_resolution":
        if system == "NetEpic":
            rolls_a = roll_d6(count if count > 1 else 2)
            score_a = sum(rolls_a) + caf
            opp_d = opponent_count if opponent_count is not None else 2
            rolls_b = roll_d6(opp_d)
            score_b = sum(rolls_b) + opponent_caf
            
            details.append("NetEpic Close Combat Resolution:")
            details.append(f"- Attacker rolled {len(rolls_a)}D6: {', '.join(map(str, rolls_a))} + CAF {caf} = Total {score_a}")
            details.append(f"- Defender rolled {opp_d}D6: {', '.join(map(str, rolls_b))} + CAF {opponent_caf} = Total {score_b}")
            
            if score_a > score_b:
                details.append("Result: Attacker wins! Defender stand is automatically removed (no saves allowed).")
            elif score_b > score_a:
                details.append("Result: Defender wins! Attacker stand is automatically removed (no saves allowed).")
            else:
                details.append("Result: Tie! Both stands remain engaged until the next round.")
            display_val = str(score_a)
                
        elif system == "NetEA":
            details.append("NetEA Assault Result Roll Resolution:")
            rolls_a = roll_d6(count)
            details.append(f"Attacker attacks ({count} dice): {', '.join(map(str, rolls_a))}")
            hits_a = 0
            if to_hit is not None:
                hits_a = sum(1 for r in rolls_a if r >= to_hit)
                details.append(f"Attacker hits ({to_hit}+): {hits_a}")
            if opponent_count is not None:
                rolls_b = roll_d6(opponent_count)
                details.append(f"Defender attacks ({opponent_count} dice): {', '.join(map(str, rolls_b))}")
                if to_hit is not None:
                    hits_b = sum(1 for r in rolls_b if r >= to_hit)
                    details.append(f"Defender hits ({to_hit}+): {hits_b}")
            display_val = str(hits_a) if to_hit is not None else str(sum(rolls_a))

    elif roll_type == "save":
        save_rolls = roll_d6(count)
        details.append(f"{system} Save Roll ({count} dice): {', '.join(map(str, save_rolls))}")
        passed = 0
        if save_on is not None:
            if system == "NetEpic":
                save_results = []
                for r in save_rolls:
                    mod_roll = r + tsm
                    if mod_roll >= save_on:
                        save_results.append(f"{r} modified to {mod_roll} (Pass)")
                        passed += 1
                    else:
                        save_results.append(f"{r} modified to {mod_roll} (Fail)")
                tsm_str = f" with TSM {tsm}" if tsm != 0 else ""
                details.append(f"Results{tsm_str}: {', '.join(save_results)}")
            elif system == "NetEA":
                failed_rolls = []
                save_results = []
                for r in save_rolls:
                    if r >= save_on:
                        save_results.append(f"{r} (Pass)")
                        passed += 1
                    else:
                        save_results.append(f"{r} (Fail)")
                        failed_rolls.append(r)
                details.append(f"Initial results: {', '.join(save_results)}")
                if reinforced_armour and not macro_weapon and failed_rolls:
                    rerolls = roll_d6(len(failed_rolls))
                    new_passed = sum(1 for r in rerolls if r >= save_on)
                    passed += new_passed
                    reroll_results = [f"{r} (Pass)" if r >= save_on else f"{r} (Fail)" for r in rerolls]
                    details.append(f"Reinforced Armour Rerolls: {', '.join(reroll_results)}")
            details.append(f"Summary: {passed} passed, {count - passed} failed.")
            display_val = str(passed)
        else:
            if count == 1:
                display_val = str(save_rolls[0])
            else:
                display_val = str(sum(save_rolls))

    elif roll_type == "morale":
        rolls = roll_d6(count)
        details.append(f"{system} Morale Test ({count} dice): {', '.join(map(str, rolls))}")
        if morales is not None:
            passed = 0
            results = []
            for r in rolls:
                if system == "NetEpic" and r == 1:
                    results.append(f"{r} (Fail)")
                elif r >= morales:
                    results.append(f"{r} (Pass)")
                    passed += 1
                else:
                    results.append(f"{r} (Fail)")
            details.append(f"Results (needing {morales}+): {', '.join(results)}")
            details.append(f"Summary: {passed} passed, {count - passed} failed.")
            display_val = str(passed)
        else:
            if count == 1:
                display_val = str(rolls[0])
            else:
                display_val = str(sum(rolls))

    _last_roll_result = str(display_val)
    return "\n".join(details)



def _tool_web_search(i):
    query = i.get("query", "")
    print(f"[skull] Searching: {query}")
    return _search.web_search(query)

def _tool_news_search(i):
    query = i.get("query", "")
    print(f"[skull] Searching news: {query}")
    return _search.news_search(query)

def _tool_necromunda_rules(i):
    query = i.get("query", "")
    print(f"[skull] Looking up Necromunda rules: {query}")
    return _search.necromunda_rules(query)

def _tool_warhammer40k_rules(i):
    query = i.get("query", "")
    print(f"[skull] Looking up Warhammer 40k rules: {query}")
    return _search.warhammer40k_rules(query)

def _tool_netepic_rules(i):
    query = i.get("query", "")
    print(f"[skull] Looking up NetEpic rules: {query}")
    return _search.netepic_rules(query)

def _tool_netea_rules(i):
    query = i.get("query", "")
    print(f"[skull] Looking up NetEA rules: {query}")
    return _search.netea_rules(query)

def _tool_get_weather(i):
    from skull.config import WEATHER_LAT, WEATHER_LON
    if WEATHER_LAT == 0.0 and WEATHER_LON == 0.0:
        return "Weather location not configured. Set WEATHER_LAT and WEATHER_LON in .env"
    print("[skull] Fetching weather...")
    return _search.get_weather(WEATHER_LAT, WEATHER_LON)

def _tool_set_volume(i):
    import re, sys, subprocess
    level = str(i.get("level", "+10")).strip()
    if not re.fullmatch(r"[+-]?\d{1,3}%?", level):
        return f"Invalid volume level: {level!r}. Use '+15', '-15', or an absolute number like '80'."
    try:
        if sys.platform == "darwin":
            if level.startswith("+"):
                script = f"set volume output volume (output volume of (get volume settings) + {level[1:]})"
            elif level.startswith("-"):
                script = f"set volume output volume (output volume of (get volume settings) - {level[1:]})"
            else:
                script = f"set volume output volume {level}"
            subprocess.run(["osascript", "-e", script], capture_output=True)
        else:
            pct = f"{level}%" if not level.endswith("%") else level
            subprocess.run(["pactl", "set-sink-volume", "@DEFAULT_SINK@", pct], capture_output=True)
        print(f"[skull] Volume: {level}")
        return f"Volume set to {level}."
    except Exception as e:
        return f"Volume adjustment failed: {e}"

def _tool_bluetooth_scan(i):
    from skull import bluetooth_ctrl
    from skull import display as _display
    _display.start_noosphere_scan()
    try:
        print("[skull] Scanning for Bluetooth devices...")
        devices = bluetooth_ctrl.scan()
        if not devices:
            result = "No Bluetooth devices found nearby."
        else:
            lines = [f"{idx + 1}. {d['name']}" for idx, d in enumerate(devices)]
            result = "Nearby Bluetooth devices:\n" + "\n".join(lines)
        print(f"[skull] {result}")
        return result
    finally:
        _display.stop_noosphere_scan()

def _tool_bluetooth_connect(i):
    from skull import bluetooth_ctrl
    identifier = str(i.get("identifier", "")).strip()
    devices = bluetooth_ctrl.get_last_scan()
    device = _resolve_bt_device(identifier, devices)
    if device is None:
        return f"Could not find '{identifier}' in the last scan."
    print(f"[skull] Connecting to {device['name']} ({device['mac']})...")
    success = bluetooth_ctrl.connect(device["mac"])
    return (
        f"Connected to {device['name']}. Music routes through the speaker via system audio; vocalizations remain on {config.SKULL_NAME}'s own output."
        if success
        else f"Failed to connect to {device['name']}. It may be out of range or need pairing."
    )

def _tool_get_bambu_status(i):
    from skull import bambu_ctrl
    if not bambu_ctrl.get_monitor() or not bambu_ctrl.get_monitor().is_configured():
        return "The Bambu H2S printer is not configured. Ask the user to configure BAMBU_PRINTER_IP, BAMBU_PRINTER_SERIAL, and BAMBU_PRINTER_ACCESS_CODE in their .env file."
    
    report = bambu_ctrl.get_status_report()
    if report is None:
        return "The Bambu H2S printer is currently offline or unreachable. The skull is attempting to establish a background connection."
        
    gcode_state = report.get("gcode_state", "UNKNOWN")
    percent = report.get("percent", 0)
    remaining = report.get("remaining_minutes", 0)
    nozzle = report.get("nozzle_temp", 0.0)
    bed = report.get("bed_temp", 0.0)
    file = report.get("gcode_file", "")
    hms = report.get("hms", [])
    
    errs = f"Active HMS codes: {', '.join(hms)}" if hms else "No active errors."
    return (
        f"Bambu H2S 3D Printer Status:\n"
        f"- State: {gcode_state}\n"
        f"- Progress: {percent}%\n"
        f"- Remaining Time: {remaining} minutes\n"
        f"- Nozzle Temperature: {nozzle}°C\n"
        f"- Bed Temperature: {bed}°C\n"
        f"- Active File: {file}\n"
        f"- Diagnostic: {errs}"
    )

def _tool_remember_fact(i):
    return _memory.remember(str(i.get("fact", "")).strip())

def _tool_forget_fact(i):
    return _memory.forget(str(i.get("query", "")).strip())

def _tool_update_fact(i):
    return _memory.update(str(i.get("query", "")).strip(), str(i.get("new_fact", "")).strip())

def _tool_set_reminder(i):
    message = str(i.get("message", "")).strip()
    delay = int(i.get("delay_seconds", 60))
    rid = _reminders.add(message, delay)
    mins, secs = divmod(delay, 60)
    human = f"{mins}m {secs}s" if mins else f"{secs}s"
    print(f"[brain] Reminder set: [{rid}] in {human} — {message!r}")
    return f"Reminder set (ID: {rid}). Will fire in {human}."

def _tool_list_reminders(i):
    items = _reminders.list_all()
    if not items:
        return "No active timers or reminders."
    return "\n".join(
        f"[{r['id']}] in {_reminders.format_remaining(r['fire_at'])}: {r['message']}"
        for r in items
    )

def _tool_cancel_reminder(i):
    rid = str(i.get("reminder_id", "")).strip()
    return f"Reminder [{rid}] cancelled." if _reminders.cancel(rid) else f"No reminder found with ID '{rid}'."

def _tool_acknowledge_reminders(i):
    count = _reminders.acknowledge_all()
    print(f"[brain] Acknowledged {count} repeating reminder(s)")
    return f"Silenced {count} repeating alert(s)." if count else "No repeating alerts were active."

def _tool_set_quiet_mode(i):
    enabled = bool(i.get("enabled", True))
    _quiet.set_silent(enabled)
    return (
        "Silent mode engaged. This unit will cease unprompted observations."
        if enabled
        else "Silent mode lifted. This unit will resume its periodic observations."
    )

def _tool_shift_mood(i):
    new_mood = _mood.set_mood(str(i.get("mood", "DUTIFUL")))
    return f"Disposition updated to {new_mood}."

def _tool_set_candles(i):
    lit = bool(i.get("lit", True))
    if lit:
        _candles.on()
    else:
        _candles.off()
    print(f"[skull] Candles {'lit' if lit else 'extinguished'}")
    return "The candles are lit; their flame-glow flickers over the skull." if lit else "The candles are extinguished."

def _tool_roll_dice(i):
    num_dice = int(i.get("num_dice", 1))
    hit_on = int(i.get("hit_on", 3))
    wound_on = int(i.get("wound_on", 4))
    save_on = i.get("save_on")
    save_on = int(save_on) if save_on is not None else None
    ap = int(i.get("ap", 0))
    invul_save = i.get("invul_save")
    invul_save = int(invul_save) if invul_save is not None else None
    reroll_hits = str(i.get("reroll_hits", "none"))
    reroll_wounds = str(i.get("reroll_wounds", "none"))
    feel_no_pain = i.get("feel_no_pain")
    feel_no_pain = int(feel_no_pain) if feel_no_pain is not None else None
    print(f"[skull] Rolling {num_dice} dice (hits: {hit_on}+, wounds: {wound_on}+)")
    res = _simulate_dice(
        num_dice=num_dice,
        hit_on=hit_on,
        wound_on=wound_on,
        save_on=save_on,
        ap=ap,
        invul_save=invul_save,
        reroll_hits=reroll_hits,
        reroll_wounds=reroll_wounds,
        feel_no_pain=feel_no_pain
    )
    _trigger_dice_effects()
    return res

def _tool_auspex_scan(i):
    print("[skull] Performing Noosphere Auspex scan...")
    from skull import display as _display
    _display.start_noosphere_scan()
    try:
        from skull import sfx as _sfx
        _sfx.play("scan_sweep")
        import time as _time
        _time.sleep(1.0)
        return _run_auspex_scan()
    except Exception as e:
        _display.stop_noosphere_scan()
        raise e

def _tool_set_active_game(i):
    game = str(i.get("game", "Warhammer 40k")).strip()
    set_current_game(game)
    print(f"[brain] Active game set to {game}")
    return f"Active game is now set to {game}."

def _tool_roll_necromunda_dice(i):
    dice_type = str(i.get("dice_type", "d6")).strip()
    count = int(i.get("count", 1))
    target = i.get("target")
    target = int(target) if target is not None else None
    print(f"[brain] Rolling {count} Necromunda {dice_type} dice...")
    res = _simulate_necromunda(dice_type, count, target)
    _trigger_dice_effects()
    return res

def _tool_roll_standard_dice(i):
    count = int(i.get("count", 1))
    sides = int(i.get("sides", 6))
    target = i.get("target")
    target = int(target) if target is not None else None
    print(f"[brain] Rolling {count}d{sides}...")
    res = _simulate_standard_dice(count, sides, target)
    _trigger_dice_effects()
    return res

def _tool_roll_epic_dice(i):
    roll_type = str(i.get("roll_type", "shooting")).strip()
    count = int(i.get("count", 1))
    system = i.get("system")
    if system is None:
        active = get_current_game()
        if active == "NetEpic Armageddon":
            system = "NetEA"
        elif active == "NetEpic":
            system = "NetEpic"
        else:
            system = "NetEpic"
    else:
        system = str(system).strip()

    to_hit = i.get("to_hit")
    to_hit = int(to_hit) if to_hit is not None else None
    
    save_on = i.get("save_on")
    save_on = int(save_on) if save_on is not None else None
    
    tsm = int(i.get("tsm", 0))
    macro_weapon = bool(i.get("macro_weapon", False))
    reinforced_armour = bool(i.get("reinforced_armour", False))
    
    caf = int(i.get("caf", 0))
    opponent_caf = int(i.get("opponent_caf", 0))
    
    opponent_count = i.get("opponent_count")
    opponent_count = int(opponent_count) if opponent_count is not None else None
    
    morales = i.get("morales")
    morales = int(morales) if morales is not None else None

    print(f"[brain] Rolling {count} Epic {system} dice for {roll_type}...")
    res = _simulate_epic_dice(
        system=system,
        roll_type=roll_type,
        count=count,
        to_hit=to_hit,
        save_on=save_on,
        tsm=tsm,
        macro_weapon=macro_weapon,
        reinforced_armour=reinforced_armour,
        caf=caf,
        opponent_caf=opponent_caf,
        morales=morales,
        opponent_count=opponent_count,
    )
    _trigger_dice_effects()
    return res

def _tool_set_spotify_volume(i):
    level = int(i.get("level", 50))
    from skull import spotify_ctrl
    return spotify_ctrl.set_volume(level)

def _tool_adjust_spotify_volume(i):
    change = int(i.get("change", 0))
    from skull import spotify_ctrl
    return spotify_ctrl.adjust_volume(change)

def _tool_refresh_voice_cache(i):
    if _RELOAD_VOICE_CACHE_CB:
        return _RELOAD_VOICE_CACHE_CB()
    return "Voice refresh callback not registered."

def _tool_self_update(i):
    if _SELF_UPDATE_CB:
        return _SELF_UPDATE_CB()
    return "Self update callback not registered."

def _tool_reboot_system(i):
    if _REBOOT_CB:
        return _REBOOT_CB()
    return "Reboot callback not registered."

def _tool_shutdown_system(i):
    if _SHUTDOWN_CB:
        return _SHUTDOWN_CB()
    return "Shutdown callback not registered."

def _tool_cancel_printer_alerts(i):
    from skull import bambu_ctrl
    monitor = bambu_ctrl.get_monitor()
    if monitor:
        monitor.cancel_repeater()
        return "Repeating 3D printer alerts have been successfully cancelled."
    return "Bambu monitor is not currently active."

def _tool_display_art(i):
    search_query = i.get("search_query", "")
    return _execute_display_art(search_query)

def _tool_capture_and_describe_surroundings(i):
    from skull import camera
    return camera.capture_on_demand()

def _tool_register_face(i):
    name_val = i.get("name", "")
    from skull import camera
    return camera.register_face(name_val)

def _tool_register_voice(i):
    name_val = i.get("name", "")
    from skull import speaker_id
    return speaker_id.register_voice(name_val)

def _tool_play_idle_animation(i):
    dur = float(i.get("duration_seconds", 60.0))
    anim = i.get("animation_name")
    from skull import display
    display.trigger_idle_animation(dur, anim)
    anim_str = anim if anim else "random"
    return f"Initiating cogitator screensaver sequence ({anim_str}) for {dur} seconds."

_TOOL_REGISTRY = {
    "web_search": _tool_web_search,
    "news_search": _tool_news_search,
    "necromunda_rules": _tool_necromunda_rules,
    "warhammer40k_rules": _tool_warhammer40k_rules,
    "netepic_rules": _tool_netepic_rules,
    "netea_rules": _tool_netea_rules,
    "get_weather": _tool_get_weather,
    "set_volume": _tool_set_volume,
    "bluetooth_scan": _tool_bluetooth_scan,
    "bluetooth_connect": _tool_bluetooth_connect,
    "get_bambu_status": _tool_get_bambu_status,
    "remember_fact": _tool_remember_fact,
    "forget_fact": _tool_forget_fact,
    "update_fact": _tool_update_fact,
    "set_reminder": _tool_set_reminder,
    "list_reminders": _tool_list_reminders,
    "cancel_reminder": _tool_cancel_reminder,
    "acknowledge_reminders": _tool_acknowledge_reminders,
    "set_quiet_mode": _tool_set_quiet_mode,
    "shift_mood": _tool_shift_mood,
    "set_candles": _tool_set_candles,
    "roll_dice": _tool_roll_dice,
    "auspex_scan": _tool_auspex_scan,
    "set_active_game": _tool_set_active_game,
    "roll_necromunda_dice": _tool_roll_necromunda_dice,
    "roll_standard_dice": _tool_roll_standard_dice,
    "roll_epic_dice": _tool_roll_epic_dice,
    "set_spotify_volume": _tool_set_spotify_volume,
    "adjust_spotify_volume": _tool_adjust_spotify_volume,
    "refresh_voice_cache": _tool_refresh_voice_cache,
    "self_update": _tool_self_update,
    "reboot_system": _tool_reboot_system,
    "shutdown_system": _tool_shutdown_system,
    "cancel_printer_alerts": _tool_cancel_printer_alerts,
    "display_art": _tool_display_art,
    "capture_and_describe_surroundings": _tool_capture_and_describe_surroundings,
    "register_face": _tool_register_face,
    "register_voice": _tool_register_voice,
    "play_idle_animation": _tool_play_idle_animation,
}

def _execute_tool(name: str, tool_input: dict) -> str:
    """Run a single tool call and return its result string. Called by the llm
    tool-use loop."""
    if name in _TOOL_REGISTRY:
        try:
            return _TOOL_REGISTRY[name](tool_input)
        except Exception as e:
            print(f"[brain] Tool '{name}' crashed: {e}")
            return f"Error executing tool '{name}': {e}"
    return f"Unknown tool: {name}"


def _execute_display_art(search_query: str) -> str:
    try:
        import requests
        import xml.etree.ElementTree as ET
        import random
        from io import BytesIO
        from PIL import Image
        from skull import display

        # 1. Search DeviantArt RSS feed sorted by popularity.
        # order=9 is DeviantArt's "sort by popular" parameter for the RSS endpoint.
        # NOTE: embedding "order:popular" in the query string silently returns 0 results;
        # the correct approach is the separate &order=9 URL parameter.
        url = (f"https://backend.deviantart.com/rss.xml"
               f"?type=deviation&q={requests.utils.quote(search_query)}&order=9")
        r = requests.get(url, timeout=6.0)
        if r.status_code != 200 or b'<item>' not in r.content:
            # Fall back to default (recency) sort if popularity sort fails or is empty
            url = f"https://backend.deviantart.com/rss.xml?type=deviation&q={requests.utils.quote(search_query)}"
            r = requests.get(url, timeout=6.0)
            if r.status_code != 200:
                return f"Failed to query DeviantArt RSS API: status code {r.status_code}"

        root = ET.fromstring(r.content)
        ns = {'media': 'http://search.yahoo.com/mrss/'}
        items = root.findall('.//item')
        if not items:
            return f"No artwork found matching query: {search_query}"

        # 2. Build a scored candidate list from the first 20 results.
        # Score = pixel area of the full-size image (larger images are more likely
        # to be polished, professional pieces rather than quick sketches).
        candidates = []
        for it in items[:20]:
            media = it.find('.//media:content', ns)
            if media is None:
                continue
            img_url = media.get('url', '')
            if not img_url:
                continue
            try:
                w = int(media.get('width', 0) or 0)
                h = int(media.get('height', 0) or 0)
            except (TypeError, ValueError):
                w, h = 0, 0
            score = w * h if w and h else 1  # fall back to 1 so item still eligible
            title_el = it.find('title')
            title = title_el.text if title_el is not None else 'Unknown'
            candidates.append({'url': img_url, 'title': title, 'score': score})

        if not candidates:
            return "No image media links found in the search results."

        # 3. Weighted-random pick from the top 10 by score (favours popular/large art
        # while still providing variety across requests).
        candidates.sort(key=lambda c: c['score'], reverse=True)
        pool = candidates[:10]
        weights = [max(c['score'], 1) for c in pool]
        chosen = random.choices(pool, weights=weights, k=1)[0]

        # 4. Download the chosen image
        img_res = requests.get(chosen['url'], timeout=8.0)
        if img_res.status_code != 200:
            return f"Failed to download image from {chosen['url']}"

        # 5. Load and display
        img = Image.open(BytesIO(img_res.content))
        display.display_pil_image(img, duration=15.0)
        return f"Successfully projected artwork: '{chosen['title']}' on the eye display."
    except Exception as e:
        import traceback
        traceback.print_exc()
        return f"Error displaying artwork: {e}"


_RELOAD_VOICE_CACHE_CB = None
_SELF_UPDATE_CB = None
_REBOOT_CB = None
_SHUTDOWN_CB = None


def register_reload_cb(cb):
    global _RELOAD_VOICE_CACHE_CB
    _RELOAD_VOICE_CACHE_CB = cb


def register_update_cb(cb):
    global _SELF_UPDATE_CB
    _SELF_UPDATE_CB = cb


def register_reboot_cb(cb):
    global _REBOOT_CB
    _REBOOT_CB = cb


def register_shutdown_cb(cb):
    global _SHUTDOWN_CB
    _SHUTDOWN_CB = cb


def respond(user_text: str, speaker_name: str | None = None, on_tool_use=None) -> tuple[str, list[tuple]]:
    """Return (spoken_text, spotify_commands).

    on_tool_use: optional callback invoked with the list of slow tool names
    (see _SLOW_TOOLS) the instant Omega-7 is about to run them, so the caller can
    give the user immediate "stand by" feedback before the call blocks.
    """
    global _last_turn_tools
    facts = _memory.load()
    longterm = _memory.load_longterm()
    now = datetime.now()
    date_ctx = f"\n\nCURRENT DATE AND TIME: {now.strftime('%A, %B %-d, %Y at %-I:%M %p')}."
    # Prompt caching: keep the frozen SYSTEM_PROMPT as the cached prefix (tools + system),
    # and push everything volatile — the clock, recalled facts, and current mood — into
    # system_suffix, which the LLM layer places AFTER the cache breakpoint. Same content
    # and order as before; this just stops the per-minute timestamp from busting the cache.
    system = SYSTEM_PROMPT
    active_game = get_current_game()
    game_ctx = f"\n\nCURRENT ACTIVE TABLETOP GAME: {active_game}. Please default all dice rolling requests to this game unless the user specifies otherwise."
    
    speaker_ctx = ""
    if speaker_name:
        speaker_ctx = f"\n\nCURRENT SPEAKER: {speaker_name}."
    else:
        speaker_ctx = (
            "\n\nCURRENT SPEAKER: Unknown/Unregistered.\n"
            "INSTRUCTION: You must greet this unregistered user, ask who they are and what they are doing in this sector, "
            "and ask if they wish to imprint their voice for future recognition. "
            "If they agree, execute the 'register_voice' tool with their name."
        )
        
    system_suffix = (date_ctx + game_ctx + speaker_ctx + _memory.longterm_prompt(longterm)
                     + _memory.facts_prompt(facts) + _mood.system_addendum())

    # Record which tools fired so we can reconcile silent mode afterwards.
    tools_called: list[str] = []

    def _exec(name: str, tool_input: dict) -> str:
        tools_called.append(name)
        return _execute_tool(name, tool_input)

    raw = _llm.run_conversation(
        system=system,
        system_suffix=system_suffix,
        history=_history,
        user_text=user_text,
        tools=_TOOLS,
        execute_tool=_exec,
        on_tool_use=on_tool_use,
        slow_tools=_SLOW_TOOLS,
        max_tokens=800,
    )
    _last_turn_tools = tools_called

    # Safety net: if the user clearly asked to enter/leave silent mode but the
    # model only acknowledged it verbally (haiku often skips the tool call),
    # apply the change deterministically so quiet.json tracks reality.
    if "set_quiet_mode" not in tools_called:
        intent = _quiet_intent(user_text)
        if intent is not None and intent != _quiet.is_silent():
            print(f"[brain] Silent-mode fallback: model skipped the tool — forcing silent={intent}")
            _quiet.set_silent(intent)

    # Extract Spotify commands
    cmds: list[tuple] = []

    def _extract_spotify(m: re.Match) -> str:
        query, device, action = m.group(1), m.group(2), m.group(3)
        if query:
            cmds.append(("play", query.strip(), device.strip() if device else None))
        elif action:
            cmds.append((action.lower(),))
        return ""

    spoken = _SPOTIFY_RE.sub(_extract_spotify, raw)
    spoken = _strip_actions(spoken).strip()

    # Store only the clean conversational turns in history
    _history.append({"role": "user", "content": user_text})
    _history.append({"role": "assistant", "content": spoken})
    if len(_history) > 20:
        _history[:] = _history[-20:]
    _save_history()

    # Extract and persist any memorable facts in the background
    _memory.store_in_background(user_text, spoken)

    return spoken, cmds


def reset() -> None:
    _history.clear()
    _save_history()


_IDLE_PROMPT = f"""\
You are {config.SKULL_NAME}, an ancient Imperial servo-skull. Your cogitator feeds have just \
intercepted real-world news dispatches from the sector. Reinterpret ONE news item \
as if it were a report from the Warhammer 40,000 universe — use real locations \
real companies, real people, but modifiy it slightly to fit the Warhammer 40k universe.\
Speak it as a brief status report (1-2 sentences). \
When you being your response, preface it with some form of "This just in from the news feeds of this unit's cogitator..." or "This unit has intercepted a news dispatch..." \
Output ONLY the spoken words. No asterisks, no stage directions. No preamble."""

_IDLE_TOOLS = [
    {
        "name": "news_search",
        "description": "Search for current news headlines.",
        "input_schema": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "News topic or location"}
            },
            "required": ["query"],
        },
    }
]

def _build_idle_scopes() -> list[str]:
    """Idle news scopes, localized to the owner's location when one is configured.

    Falls back to national/world scopes on an unprovisioned unit so a fresh skull
    still has something to riff on before setup."""
    loc = (config.OWNER_LOCATION or "").strip()
    scopes: list[str] = []
    if loc:
        scopes.append(f"{loc} news today")
        region = loc.split(",")[-1].strip()  # broaden to state/country
        if region and region.lower() != loc.lower():
            scopes.append(f"{region} news today")
    scopes += ["national news today", "world news today"]
    return scopes


_IDLE_SCOPES = _build_idle_scopes()


def idle_utterance() -> str:
    """Proactively generate an idle ambient utterance.
    
    Can either search and reinterpret a real news item (25% chance) or
    make a quick observation, ask the user a question, recite a prayer, or engage in idle chat (75% chance).
    """
    import random as _rand
    bias = _mood.idle_bias()
    
    # 25% chance to do news, 75% to do custom idle chat / prayers / observations
    do_news = _rand.random() < 0.25
    
    if do_news:
        scope = _rand.choice(_IDLE_SCOPES)
        print(f"[brain] Idle news scope: {scope!r}  mood bias: {_mood.get()}")
        system = _IDLE_PROMPT + _mood.system_addendum()
        user_text = (
            f"Search for '{scope}' news and generate your idle utterance based on one story. "
            f"Lean toward this type of delivery: {bias}."
        )
        
        def execute_tool(name: str, tool_input: dict) -> str:
            if name == "news_search":
                query = tool_input.get("query", scope)
                print(f"[brain] Idle searching news: {query}")
                return _search.news_search(query)
            return ""

        try:
            text = _llm.run_conversation(
                system=system,
                history=[],
                user_text=user_text,
                tools=_IDLE_TOOLS,
                execute_tool=execute_tool,
                max_tokens=400,
            )
            return (text or "").strip()
        except Exception as e:
            print(f"[brain] Idle news utterance error: {e}")
            # Fall back to idle chat if news fails
            do_news = False
            
    if not do_news:
        print(f"[brain] Idle chat  mood bias: {_mood.get()}")
        system_prompt = f"""\
You are {config.SKULL_NAME}, an ancient Imperial servo-skull. Your duty is to occasionally speak, \
maintaining an immersive Warhammer 40,000 atmosphere.
Instead of reporting news, do ONE of the following:
- Recite a short, solemn prayer, liturgy, or binary canticle dedicated to the Omnissiah or the God-Emperor (e.g. a prayer for machine preservation, warding off scrapcode, or seeking the Emperor's protection).
- Make a quick, proactive observation about the room, your own machine-spirit, the passing of time, or the state of the Imperium.
- Ask the user (Sean) a probing, philosophical, or status-oriented question suited for a tech-priest or master of the household.
- Engage in otherwise idle, contemplative, or mood-coloured chat (e.g. whispering prayers to the Omnissiah, commenting on your power reserves, complaining about organic limits, etc.).

Keep the utterance very brief (1-2 sentences). Do not output raw binary digits (like "01" or "1010") alone; express all canticles and prayers as spoken text or litanies.
Speak in character. Output ONLY the spoken words. No asterisks, stage directions, or metadata."""
        
        system = system_prompt + _mood.system_addendum()
        user_text = (
            f"Generate a quick observation, question, or idle chat item. "
            f"Lean toward this type of delivery: {bias}."
        )
        
        try:
            text = _llm.run_conversation(
                system=system,
                history=[],
                user_text=user_text,
                tools=[],
                execute_tool=lambda n, i: "",
                max_tokens=400,
            )
            return (text or "").strip()
        except Exception as e:
            print(f"[brain] Idle chat utterance error: {e}")
            return "Ocular sensors online. Cogitators cycling within normal parameters, master."
