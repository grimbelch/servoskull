"""Warhammer Fantasy Roleplay 4E (WFRP) modular roleplaying game system.

Provides:
- tools: List of tool schemas and handler dispatch map
- persona_prompt: Returns persona text for GM mode & character creation
- campaign: Campaign memory manager and character sheet persistence
- search: Offline rules search engine
- foundry: Optional Foundry VTT bridge (enable with FOUNDRY_MCP_ENABLED=true)
"""
from __future__ import annotations

import pathlib
from . import campaign
from . import search
from . import tools
from . import foundry


def get_persona_prompt() -> str:
    """Return the WFRP GM mode system prompt and character creation protocol."""
    p = pathlib.Path(__file__).parent / "persona.txt"
    if p.exists():
        return p.read_text(encoding="utf-8")
    return ""


__all__ = ["campaign", "search", "tools", "foundry", "get_persona_prompt"]
