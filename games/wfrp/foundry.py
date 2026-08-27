"""Foundry VTT bridge — exposes Foundry MCP tools to Omega-7's Claude tool loop.

Omega-7 talks to a local ``foundry-mcp-server`` process over stdio JSON-RPC
(the Model Context Protocol). That server in turn holds a WebSocket open to the
``foundry-mcp-bridge`` module running inside a logged-in Gamemaster browser
session, which is what actually mutates the Foundry world.

    Omega-7 (this module)
        -> stdio JSON-RPC -> foundry-mcp-server (node)
        -> WebSocket :31415 -> foundry-mcp-bridge (GM browser)
        -> Foundry world

Because the last hop lives in a browser, **a GM client must be open and logged
in** for any of these tools to work. When it isn't, calls return a structured
error rather than raising, so the machine-spirit can explain itself out loud
instead of falling over mid-session.

Tool schemas are read from ``foundry_tools.json`` so importing this module never
spawns a subprocess; the node process is started lazily on first use.
"""
from __future__ import annotations

import json
import logging
import os
import pathlib
import subprocess
import threading
import time
from typing import Any, Dict, List, Optional

log = logging.getLogger(__name__)

_HERE = pathlib.Path(__file__).parent
_SCHEMA_CACHE = _HERE / "foundry_tools.json"

# Prefix keeps Foundry tools from colliding with the offline whfrp_* tools and
# makes it obvious in logs which side of the house a call went to.
_PREFIX = "foundry_"

# MCP protocol version this client negotiates.
_PROTOCOL_VERSION = "2024-11-05"

# Tools surfaced to Claude by default. The bridge ships 43, but most are for
# other game systems (dnd5e-*, dsa5-*) or bulk world-building, and every schema
# we expose costs prompt tokens on every single request. This set is scoped to
# what a GM actually says out loud at a WFRP table.
DEFAULT_TOOLS = (
    "get-world-info",
    "get-current-scene",
    "list-scenes",
    "switch-scene",
    "list-characters",
    "get-character",
    "get-token-details",
    "move-token",
    "toggle-token-condition",
    "get-available-conditions",
    "request-player-rolls",
    "search-compendium",
    "create-actor-from-compendium",
    "wfrp4e-update-actor",
    "wfrp4e-add-items",
    "list-journals",
    "search-journals",
)


def _cfg(key: str, default: str) -> str:
    """Read a setting from core.config when available, else the environment."""
    try:
        from core import config as _core_config

        value = _core_config._cfg(key, default)  # noqa: SLF001 - shared accessor
        if value is not None:
            return str(value)
    except Exception:
        pass
    return os.getenv(key, default)


def _flag(key: str, default: str = "false") -> bool:
    return _cfg(key, default).strip().lower() in ("1", "true", "yes", "on")


ENABLED = _flag("FOUNDRY_MCP_ENABLED", "false")
SERVER_DIR = pathlib.Path(
    _cfg("FOUNDRY_MCP_SERVER_DIR", "~/foundry-mcp-server")
).expanduser()
NODE_BIN = _cfg("FOUNDRY_MCP_NODE", "node")
CALL_TIMEOUT = float(_cfg("FOUNDRY_MCP_TIMEOUT", "30"))
# Foundry's own reconnect budget is short; give the browser a moment to attach
# before declaring the table dead.
STARTUP_TIMEOUT = float(_cfg("FOUNDRY_MCP_STARTUP_TIMEOUT", "45"))


def _entry_point() -> Optional[pathlib.Path]:
    """Locate the server entry point, preferring the CommonJS bundle.

    The upstream standalone ZIP ships ``index.js`` alongside a
    ``"type": "module"`` package.json, which makes node refuse to load it. The
    desktop installers ship ``index.cjs``, which works. Prefer the latter.
    """
    for name in ("index.cjs", "index.js"):
        candidate = SERVER_DIR / name
        if candidate.exists():
            return candidate
    return None


class FoundryBridgeError(RuntimeError):
    """Raised for transport-level failures talking to the MCP server."""


class _MCPClient:
    """Minimal MCP stdio client: spawn, handshake, call tools, survive crashes."""

    def __init__(self) -> None:
        self._proc: Optional[subprocess.Popen] = None
        self._lock = threading.Lock()
        self._pending: Dict[int, dict] = {}
        self._next_id = 1
        self._reader: Optional[threading.Thread] = None
        self._stderr_tail: List[str] = []

    # -- lifecycle ---------------------------------------------------------

    def _alive(self) -> bool:
        return self._proc is not None and self._proc.poll() is None

    def _spawn(self) -> None:
        entry = _entry_point()
        if entry is None:
            raise FoundryBridgeError(
                f"No MCP server entry point under {SERVER_DIR}. "
                "Expected index.cjs (from the desktop installer payload)."
            )

        self._proc = subprocess.Popen(
            [NODE_BIN, entry.name],
            cwd=str(SERVER_DIR),
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            bufsize=1,
        )
        self._pending.clear()
        self._stderr_tail = []

        self._reader = threading.Thread(target=self._read_loop, daemon=True)
        self._reader.start()
        threading.Thread(target=self._drain_stderr, daemon=True).start()

        self._request(
            "initialize",
            {
                "protocolVersion": _PROTOCOL_VERSION,
                "capabilities": {},
                "clientInfo": {"name": "omega7", "version": "1.0"},
            },
            timeout=STARTUP_TIMEOUT,
        )
        self._notify("notifications/initialized", {})
        log.info("Foundry MCP server started (%s)", entry)

    def _ensure(self) -> None:
        if not self._alive():
            self._spawn()

    def close(self) -> None:
        with self._lock:
            if self._proc is not None:
                try:
                    self._proc.terminate()
                    self._proc.wait(timeout=5)
                except Exception:
                    try:
                        self._proc.kill()
                    except Exception:
                        pass
                self._proc = None

    # -- plumbing ----------------------------------------------------------

    def _read_loop(self) -> None:
        proc = self._proc
        if proc is None or proc.stdout is None:
            return
        for line in proc.stdout:
            line = line.strip()
            if not line:
                continue
            try:
                message = json.loads(line)
            except ValueError:
                continue
            if "id" in message:
                self._pending[message["id"]] = message

    def _drain_stderr(self) -> None:
        proc = self._proc
        if proc is None or proc.stderr is None:
            return
        for line in proc.stderr:
            self._stderr_tail.append(line)
            del self._stderr_tail[:-20]

    def _write(self, payload: dict) -> None:
        proc = self._proc
        if proc is None or proc.stdin is None:
            raise FoundryBridgeError("MCP server is not running")
        proc.stdin.write(json.dumps(payload) + "\n")
        proc.stdin.flush()

    def _notify(self, method: str, params: dict) -> None:
        self._write({"jsonrpc": "2.0", "method": method, "params": params})

    def _request(self, method: str, params: dict, timeout: float) -> dict:
        request_id = self._next_id
        self._next_id += 1
        self._write(
            {"jsonrpc": "2.0", "id": request_id, "method": method, "params": params}
        )

        deadline = time.time() + timeout
        while time.time() < deadline:
            if request_id in self._pending:
                message = self._pending.pop(request_id)
                if "error" in message:
                    raise FoundryBridgeError(str(message["error"]))
                return message.get("result", {})
            if not self._alive():
                tail = "".join(self._stderr_tail[-5:]).strip()
                raise FoundryBridgeError(
                    f"MCP server exited unexpectedly. {tail}".strip()
                )
            time.sleep(0.05)

        self._pending.pop(request_id, None)
        raise FoundryBridgeError(f"Timed out after {timeout:.0f}s waiting for {method}")

    # -- public API --------------------------------------------------------

    def call_tool(self, name: str, arguments: dict) -> dict:
        with self._lock:
            self._ensure()
            return self._request(
                "tools/call",
                {"name": name, "arguments": arguments or {}},
                timeout=CALL_TIMEOUT,
            )

    def list_tools(self) -> List[dict]:
        with self._lock:
            self._ensure()
            result = self._request("tools/list", {}, timeout=CALL_TIMEOUT)
            return result.get("tools", [])


_client = _MCPClient()


def shutdown() -> None:
    """Stop the MCP server subprocess (used on Omega-7 shutdown)."""
    _client.close()


# -- schema loading --------------------------------------------------------


def _selected_names() -> List[str]:
    override = _cfg("FOUNDRY_MCP_TOOLS", "").strip()
    if override:
        return [n.strip() for n in override.split(",") if n.strip()]
    return list(DEFAULT_TOOLS)


def _load_cached_schemas() -> List[dict]:
    if not _SCHEMA_CACHE.exists():
        log.warning("Foundry tool schema cache missing: %s", _SCHEMA_CACHE)
        return []
    try:
        return json.loads(_SCHEMA_CACHE.read_text(encoding="utf-8")).get("tools", [])
    except Exception as exc:
        log.warning("Could not read Foundry tool schema cache: %s", exc)
        return []


def omega_name(mcp_name: str) -> str:
    """``search-compendium`` -> ``foundry_search_compendium``."""
    return _PREFIX + mcp_name.replace("-", "_")


def _build_tools() -> tuple[List[dict], Dict[str, str]]:
    """Return (Anthropic tool schemas, omega_name -> mcp_name)."""
    if not ENABLED:
        return [], {}

    by_name = {t["name"]: t for t in _load_cached_schemas()}
    tools: List[dict] = []
    mapping: Dict[str, str] = {}

    for mcp_name in _selected_names():
        schema = by_name.get(mcp_name)
        if schema is None:
            log.warning("Foundry tool %r not present in schema cache; skipping", mcp_name)
            continue
        local = omega_name(mcp_name)
        tools.append(
            {
                "name": local,
                "description": schema.get("description", ""),
                "input_schema": schema.get("inputSchema", {"type": "object", "properties": {}}),
            }
        )
        mapping[local] = mcp_name

    return tools, mapping


TOOLS, _NAME_MAP = _build_tools()

# Every Foundry call crosses a subprocess, a WebSocket and a browser, so they
# are all "slow" by Omega-7's standards and should be announced before running.
SLOW_TOOLS = set(_NAME_MAP)


def _flatten(result: dict) -> Any:
    """Turn an MCP tool result into something the tool loop can serialise.

    MCP returns ``{"content": [{"type": "text", "text": "..."}]}``; the text is
    usually itself JSON, so parse it back when possible.
    """
    if result.get("isError"):
        texts = [c.get("text", "") for c in result.get("content", []) if c.get("type") == "text"]
        return {"error": " ".join(texts).strip() or "Unknown Foundry error"}

    texts = [c.get("text", "") for c in result.get("content", []) if c.get("type") == "text"]
    if not texts:
        return result

    joined = "\n".join(texts).strip()
    try:
        return json.loads(joined)
    except ValueError:
        return {"result": joined}


def _make_handler(local_name: str):
    mcp_name = _NAME_MAP[local_name]

    def handler(payload: dict) -> Any:
        try:
            return _flatten(_client.call_tool(mcp_name, payload or {}))
        except FoundryBridgeError as exc:
            log.warning("Foundry tool %s failed: %s", mcp_name, exc)
            return {
                "error": str(exc),
                "hint": (
                    "The Foundry bridge is unreachable. Confirm the world is open "
                    "in a logged-in Gamemaster browser session and that the MCP "
                    "bridge module reports Connected."
                ),
            }
        except Exception as exc:  # defensive: never kill the tool loop mid-game
            log.exception("Unexpected Foundry bridge failure")
            return {"error": f"Unexpected Foundry bridge failure: {exc}"}

    handler.__name__ = f"_tool_{local_name}"
    return handler


HANDLERS = {name: _make_handler(name) for name in _NAME_MAP}


def refresh_schema_cache() -> int:
    """Re-query the live MCP server and rewrite ``foundry_tools.json``.

    Returns the number of tools written. Requires the node server to be
    installed locally; a GM browser session is *not* needed for this.
    """
    tools = sorted(_client.list_tools(), key=lambda t: t.get("name", ""))
    payload = {
        "_comment": (
            "Cached MCP tool schemas from foundry-mcp-bridge. "
            "Regenerate with: python -m games.wfrp.foundry --refresh"
        ),
        "tools": tools,
    }
    _SCHEMA_CACHE.write_text(json.dumps(payload, separators=(",", ":")), encoding="utf-8")
    return len(tools)


def status() -> dict:
    """Cheap health probe for the web remote / diagnostics."""
    info: dict = {
        "enabled": ENABLED,
        "server_dir": str(SERVER_DIR),
        "entry_point": str(_entry_point() or ""),
        "exposed_tools": len(TOOLS),
    }
    if not ENABLED:
        info["detail"] = "Set FOUNDRY_MCP_ENABLED=true to activate."
        return info
    try:
        world = _flatten(_client.call_tool("get-world-info", {}))
        info["connected"] = "error" not in world
        info["world"] = world
    except Exception as exc:
        info["connected"] = False
        info["detail"] = str(exc)
    return info


if __name__ == "__main__":  # pragma: no cover - operator utility
    import sys

    if "--refresh" in sys.argv:
        print(f"Cached {refresh_schema_cache()} tool schemas to {_SCHEMA_CACHE}")
    else:
        print(json.dumps(status(), indent=2))
    shutdown()
