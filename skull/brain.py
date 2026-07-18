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

_history: list[dict] = []

# Tools that hit the network/hardware and can take a noticeable moment. Omega-7
# speaks a short "stand by" before running any of these so the user gets feedback.
_SLOW_TOOLS = {"web_search", "news_search", "necromunda_rules", "warhammer40k_rules", "netepic_rules", "netea_rules", "get_weather", "bluetooth_scan", "auspex_scan"}
_HISTORY_PATH = config.data_path(config.HISTORY_FILE)


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

_TOOLS = [
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
        "description": "Configure which tabletop game is currently being played (e.g. 'Warhammer 40k' or 'Necromunda') so that dice rolls default to that game context.",
        "input_schema": {
            "type": "object",
            "properties": {
                "game": {
                    "type": "string",
                    "enum": ["Warhammer 40k", "Necromunda"],
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
    }
]

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

    wound_msg = f"Wound roll: {total_hits} dice needing {wound_on}+ -> {initial_wounds} initial wounds."
    if reroll_wounds != "none" and rerolled_wounds_count > 0:
        wound_msg += f" Rerolled {rerolled_wounds_count} {reroll_wounds} -> +{new_wounds} wounds."
    wound_msg += f" Total wounds: {total_wounds}."
    details.append(wound_msg)

    if total_wounds == 0:
        details.append("No wounds generated. The attack sequence terminates.")
        return "\n".join(details)

    # Saves
    if save_on is None:
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

    save_details_msg = f"using {save_on}+ base save modified by AP {ap_val} to {modified_save}+"
    if invul_save is not None:
        save_details_msg += f" (invul {invul_save}++ available)"

    save_msg = f"Save roll: Target rolled {total_wounds} {save_type} saves needing {final_save}+ ({save_details_msg}) -> {passed_saves} passed, {failed_saves} failed."
    details.append(save_msg)

    if failed_saves == 0:
        details.append("All saves succeeded. No damage inflicted.")
        return "\n".join(details)

    # Feel No Pain
    if feel_no_pain is not None:
        fnp_rolls = roll_d6(failed_saves)
        passed_fnps = sum(1 for r in fnp_rolls if r >= feel_no_pain)
        final_damage = failed_saves - passed_fnps

        fnp_msg = f"Feel No Pain: Target rolled {failed_saves} FNP rolls needing {feel_no_pain}+ -> {passed_fnps} ignored, {final_damage} final damage inflicted."
        details.append(fnp_msg)
    else:
        details.append(f"Result: {failed_saves} damage inflicted.")

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


def _trigger_dice_effects(display_val: int | None = None) -> None:
    try:
        from skull import sfx as _sfx
        _sfx.play("dice_roll")
    except Exception as e:
        print(f"[brain] SFX play failed: {e}")

    try:
        import random as _rand
        val = display_val if display_val is not None else _rand.randint(1, 6)
        from skull import display as _display
        _display.start_die_roll(val)
    except Exception as e:
        print(f"[brain] Display roll failed: {e}")

    import time as _time
    _time.sleep(1.5)


def _simulate_necromunda(dice_type: str, count: int, target: int | None = None) -> str:
    import random
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
        
    elif dice_type == "location":
        locations = ["Head", "Body", "Left Arm", "Right Arm", "Left Leg", "Right Leg"]
        rolls = []
        for _ in range(count):
            r = random.randint(1, 6)
            rolls.append(locations[r - 1])
        
        details.append(f"Necromunda Hit Location Roll ({count} dice):")
        details.append(f"Individual rolls: {', '.join(rolls)}")
        
    elif dice_type == "d6":
        rolls = [random.randint(1, 6) for _ in range(count)]
        details.append(f"Standard D6 Roll ({count} dice): {', '.join(map(str, rolls))}")
        if target is not None:
            successes = sum(1 for r in rolls if r >= target)
            details.append(f"Successes ({target}+): {successes} passed, {count - successes} failed")
            
    return "\n".join(details)


def _simulate_standard_dice(count: int, sides: int, target: int | None = None) -> str:
    import random
    rolls = [random.randint(1, sides) for _ in range(count)]
    total = sum(rolls)
    details = [f"Rolled {count}d{sides}: {', '.join(map(str, rolls))} (Total: {total})"]
    if target is not None:
        successes = sum(1 for r in rolls if r >= target)
        details.append(f"Successes ({target}+): {successes} passed, {count - successes} failed")
    return "\n".join(details)


def _execute_tool(name: str, tool_input: dict) -> str:
    """Run a single tool call and return its result string. Called by the llm
    tool-use loop."""
    if name == "web_search":
        query = tool_input.get("query", "")
        print(f"[skull] Searching: {query}")
        return _search.web_search(query)
    if name == "news_search":
        query = tool_input.get("query", "")
        print(f"[skull] Searching news: {query}")
        return _search.news_search(query)
    if name == "necromunda_rules":
        query = tool_input.get("query", "")
        print(f"[skull] Looking up Necromunda rules: {query}")
        return _search.necromunda_rules(query)
    if name == "warhammer40k_rules":
        query = tool_input.get("query", "")
        print(f"[skull] Looking up Warhammer 40k rules: {query}")
        return _search.warhammer40k_rules(query)
    if name == "netepic_rules":
        query = tool_input.get("query", "")
        print(f"[skull] Looking up NetEpic rules: {query}")
        return _search.netepic_rules(query)
    if name == "netea_rules":
        query = tool_input.get("query", "")
        print(f"[skull] Looking up NetEA rules: {query}")
        return _search.netea_rules(query)
    if name == "get_weather":
        from skull.config import WEATHER_LAT, WEATHER_LON
        if WEATHER_LAT == 0.0 and WEATHER_LON == 0.0:
            return "Weather location not configured. Set WEATHER_LAT and WEATHER_LON in .env"
        print("[skull] Fetching weather...")
        return _search.get_weather(WEATHER_LAT, WEATHER_LON)
    if name == "set_volume":
        level = str(tool_input.get("level", "+10")).strip()
        # `level` is model-generated and gets interpolated into an osascript -e
        # string below, so reject anything that isn't a bare (optionally signed,
        # optionally %-suffixed) integer — otherwise a crafted value could inject
        # arbitrary AppleScript / shell commands.
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
    if name == "bluetooth_scan":
        from skull import bluetooth_ctrl
        from skull import display as _display
        _display.start_noosphere_scan()
        try:
            print("[skull] Scanning for Bluetooth devices...")
            devices = bluetooth_ctrl.scan()
            if not devices:
                result = "No Bluetooth devices found nearby."
            else:
                lines = [f"{i + 1}. {d['name']}" for i, d in enumerate(devices)]
                result = "Nearby Bluetooth devices:\n" + "\n".join(lines)
            print(f"[skull] {result}")
            return result
        finally:
            _display.stop_noosphere_scan()
    if name == "bluetooth_connect":
        from skull import bluetooth_ctrl
        identifier = str(tool_input.get("identifier", "")).strip()
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
    if name == "remember_fact":
        return _memory.remember(str(tool_input.get("fact", "")).strip())
    if name == "forget_fact":
        return _memory.forget(str(tool_input.get("query", "")).strip())
    if name == "update_fact":
        return _memory.update(str(tool_input.get("query", "")).strip(),
                              str(tool_input.get("new_fact", "")).strip())
    if name == "set_reminder":
        message = str(tool_input.get("message", "")).strip()
        delay = int(tool_input.get("delay_seconds", 60))
        rid = _reminders.add(message, delay)
        mins, secs = divmod(delay, 60)
        human = f"{mins}m {secs}s" if mins else f"{secs}s"
        print(f"[brain] Reminder set: [{rid}] in {human} — {message!r}")
        return f"Reminder set (ID: {rid}). Will fire in {human}."
    if name == "list_reminders":
        items = _reminders.list_all()
        if not items:
            return "No active timers or reminders."
        return "\n".join(
            f"[{r['id']}] in {_reminders.format_remaining(r['fire_at'])}: {r['message']}"
            for r in items
        )
    if name == "cancel_reminder":
        rid = str(tool_input.get("reminder_id", "")).strip()
        return f"Reminder [{rid}] cancelled." if _reminders.cancel(rid) else f"No reminder found with ID '{rid}'."
    if name == "acknowledge_reminders":
        count = _reminders.acknowledge_all()
        print(f"[brain] Acknowledged {count} repeating reminder(s)")
        return f"Silenced {count} repeating alert(s)." if count else "No repeating alerts were active."
    if name == "set_quiet_mode":
        enabled = bool(tool_input.get("enabled", True))
        _quiet.set_silent(enabled)
        return (
            "Silent mode engaged. This unit will cease unprompted observations."
            if enabled
            else "Silent mode lifted. This unit will resume its periodic observations."
        )
    if name == "shift_mood":
        new_mood = _mood.set_mood(str(tool_input.get("mood", "DUTIFUL")))
        return f"Disposition updated to {new_mood}."
    if name == "set_candles":
        lit = bool(tool_input.get("lit", True))
        if lit:
            _candles.on()
        else:
            _candles.off()
        print(f"[skull] Candles {'lit' if lit else 'extinguished'}")
        return (
            "The candles are lit; their flame-glow flickers over the skull."
            if lit
            else "The candles are extinguished."
        )
    if name == "roll_dice":
        num_dice = int(tool_input.get("num_dice", 1))
        hit_on = int(tool_input.get("hit_on", 3))
        wound_on = int(tool_input.get("wound_on", 4))
        save_on = tool_input.get("save_on")
        save_on = int(save_on) if save_on is not None else None
        ap = int(tool_input.get("ap", 0))
        invul_save = tool_input.get("invul_save")
        invul_save = int(invul_save) if invul_save is not None else None
        reroll_hits = str(tool_input.get("reroll_hits", "none"))
        reroll_wounds = str(tool_input.get("reroll_wounds", "none"))
        feel_no_pain = tool_input.get("feel_no_pain")
        feel_no_pain = int(feel_no_pain) if feel_no_pain is not None else None
        print(f"[skull] Rolling {num_dice} dice (hits: {hit_on}+, wounds: {wound_on}+)")
        _trigger_dice_effects()
        return _simulate_dice(
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
    if name == "auspex_scan":
        print("[skull] Performing Noosphere Auspex scan...")
        from skull import display as _display
        _display.start_auspex_scan()
        try:
            # Play scan sweep sound
            from skull import sfx as _sfx
            _sfx.play("scan_sweep")
            # Pause to simulate auspex sweeping
            import time as _time
            _time.sleep(1.0)
            return _run_auspex_scan()
        finally:
            _display.stop_auspex_scan()
    if name == "set_active_game":
        game = str(tool_input.get("game", "Warhammer 40k")).strip()
        set_current_game(game)
        print(f"[brain] Active game set to {game}")
        return f"Active game is now set to {game}."
    if name == "roll_necromunda_dice":
        dice_type = str(tool_input.get("dice_type", "d6")).strip()
        count = int(tool_input.get("count", 1))
        target = tool_input.get("target")
        target = int(target) if target is not None else None
        print(f"[brain] Rolling {count} Necromunda {dice_type} dice...")
        _trigger_dice_effects()
        return _simulate_necromunda(dice_type, count, target)
    if name == "roll_standard_dice":
        count = int(tool_input.get("count", 1))
        sides = int(tool_input.get("sides", 6))
        target = tool_input.get("target")
        target = int(target) if target is not None else None
        print(f"[brain] Rolling {count}d{sides}...")
        _trigger_dice_effects()
        return _simulate_standard_dice(count, sides, target)
    return f"Unknown tool: {name}"


def respond(user_text: str, on_tool_use=None) -> tuple[str, list[tuple]]:
    """Return (spoken_text, spotify_commands).

    on_tool_use: optional callback invoked with the list of slow tool names
    (see _SLOW_TOOLS) the instant Omega-7 is about to run them, so the caller can
    give the user immediate "stand by" feedback before the call blocks.
    """
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
    system_suffix = (date_ctx + game_ctx + _memory.longterm_prompt(longterm)
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
    """Fetch a real news item, reinterpret it through a 40k lens, coloured by current mood."""
    import random as _rand
    scope = _rand.choice(_IDLE_SCOPES)
    bias = _mood.idle_bias()
    print(f"[brain] Idle — scope: {scope!r}  mood bias: {_mood.get()}")
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
        print(f"[brain] Idle utterance error: {e}")
        return ""
