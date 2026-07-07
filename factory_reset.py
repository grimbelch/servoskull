#!/usr/bin/env python3
"""Factory reset — wipe all per-unit personalization and runtime state.

Returns a skull to its unprovisioned, out-of-box condition: no owner profile, no
keys, no memory, no mood/quiet/reminder/history state. The shipped character
persona (persona_template.txt) and hardware config are untouched.

Removes files from OMEGA7_DATA_DIR (defaults to the repo root; see config.py).

Usage:
    python factory_reset.py --yes        # perform the reset
    python factory_reset.py              # dry run: list what would be removed
"""

from __future__ import annotations

import sys

from skull import config

# Per-unit state written at runtime or setup. Everything here is safe to delete;
# the app recreates whatever it needs on next start.
_TARGETS = [
    "owner.json",            # personalization written by the wizard
    "settings.json",         # API keys + user settings written by the wizard
    "memory.json",           # auto-extracted facts
    "longterm_memory.json",  # explicitly remembered facts
    "history.json",          # recent conversation turns
    "reminders.json",        # pending timers/reminders
    "mood.json",             # current disposition
    "quiet.json",            # silent-mode flag
    ".spotify_cache",        # Spotify OAuth token cache
]
# Corruption-recovery sidecars for any of the above.
_BAK_SUFFIX = ".bak"


def _candidates():
    for name in _TARGETS:
        yield config.data_path(name)
        yield config.data_path(name + _BAK_SUFFIX)


def main() -> int:
    do_it = "--yes" in sys.argv or "-y" in sys.argv
    present = [p for p in _candidates() if p.exists()]

    if not present:
        print(f"[factory_reset] Nothing to remove in {config.USER_DATA_DIR}. Already clean.")
        return 0

    if not do_it:
        print(f"[factory_reset] DRY RUN — would remove {len(present)} file(s) from "
              f"{config.USER_DATA_DIR}:")
        for p in present:
            print(f"  - {p.name}")
        print("\nRe-run with --yes to perform the reset.")
        return 0

    removed = 0
    for p in present:
        try:
            p.unlink()
            print(f"[factory_reset] removed {p.name}")
            removed += 1
        except Exception as e:
            print(f"[factory_reset] FAILED to remove {p.name}: {e}")
    print(f"[factory_reset] Done — {removed} file(s) removed. Unit is unprovisioned.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
