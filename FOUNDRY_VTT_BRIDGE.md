# Foundry VTT Bridge

Lets Omega-7 read and drive a live **Foundry VTT** table instead of only
narrating from the offline rules database. Foundry supplies the canvas, maps,
tokens and the real WFRP4e rules engine; Omega-7 remains the Game Master.

Disabled by default. With `FOUNDRY_MCP_ENABLED` unset, nothing changes.

## How it fits together

```
Omega-7 (games/wfrp/foundry.py)
  --> stdio JSON-RPC --> foundry-mcp-server (node)
  --> WebSocket :31415 --> foundry-mcp-bridge (Gamemaster browser)
  --> Foundry world
```

**A logged-in Gamemaster browser session must be open.** The Foundry module is
client-side, so there is no headless path — if the GM tab closes, the bridge
goes dark. Omega-7 returns a structured `error` + `hint` in that case rather
than raising, so a session degrades to plain narration instead of crashing.

Because the MCP server speaks stdio, it must be a **child of Omega-7** and
therefore runs on the Pi — not on the Foundry server.

## Installing the server (on the Pi)

Requires Node 18+ (`sudo apt install nodejs` on Debian 13 ships Node 20).

> **Do not use `foundry-mcp-server-vX.Y.Z.zip` from the GitHub releases page.**
> It ships the wrapper without `backend.bundle.cjs`, so it hangs silently
> forever with no log output. Take the payload from the desktop installer
> instead.

```bash
# From the macOS installer (or the equivalent files from the Windows .exe)
curl -LO https://github.com/adambdooley/foundry-vtt-mcp/releases/download/v0.8.3/FoundryMCPServer-v0.8.3.dmg
hdiutil attach -nobrowse -readonly FoundryMCPServer-v0.8.3.dmg
pkgutil --expand-full "/Volumes/Foundry MCP Server 0.8.3/FoundryMCPServer-0.8.3-macOS.pkg" pkgx

APP=pkgx/FoundryMCP-Core.pkg/Payload/Applications/FoundryMCPServer.app
scp $APP/Contents/Resources/foundry-mcp-server/{backend.bundle.cjs,index.cjs,package.json} \
    omega7:~/foundry-mcp-server/
```

The payload is pure JavaScript with no native modules, so it runs fine on
aarch64. Use `index.cjs` as the entry point — `index.js` is CommonJS shipped
alongside a `"type": "module"` package.json and node refuses to load it.

## Installing the Foundry module

Drop the module into your Foundry data directory and restart:

```bash
curl -LO https://github.com/adambdooley/foundry-vtt-mcp/releases/download/v0.8.3/foundry-vtt-mcp.zip
unzip foundry-vtt-mcp.zip -d /path/to/foundrydata/Data/modules/foundry-mcp-bridge
```

Then in the world: **Manage Modules → Foundry MCP Bridge → enable**, and under
**Configure Settings → Foundry MCP Bridge**:

| Setting | Value |
| :--- | :--- |
| Enable MCP Bridge | checked |
| Connection Type | `WebSocket (Local Only)` |
| Websocket Server Host | the Pi's IP, e.g. `192.168.0.108` |

The module only retries **5 times, 1 second apart**, after the world loads. If
Omega-7 was not running at that moment, reload the browser tab — it is almost
always the explanation for a bridge that "won't connect".

## Configuration

| Setting | Default | Meaning |
| :--- | :--- | :--- |
| `FOUNDRY_MCP_ENABLED` | `false` | Master switch |
| `FOUNDRY_MCP_SERVER_DIR` | `~/foundry-mcp-server` | Where `index.cjs` lives |
| `FOUNDRY_MCP_NODE` | `node` | Node binary |
| `FOUNDRY_MCP_TIMEOUT` | `30` | Per-call timeout (seconds) |
| `FOUNDRY_MCP_STARTUP_TIMEOUT` | `45` | Handshake timeout |
| `FOUNDRY_MCP_TOOLS` | *(unset)* | Comma-separated override of the exposed tool set |

Check it from the Pi:

```bash
FOUNDRY_MCP_ENABLED=true python -m games.wfrp.foundry
```

## Exposed tools

The bridge publishes 43 tools; Omega-7 exposes **17** by default. The rest are
for other game systems (`dnd5e-*`, `dsa5-*`), bulk world-building, or AI map
generation. Every schema costs prompt tokens on *every* request — the default
set already adds roughly **5k tokens**, so widen it deliberately.

Scenes (`get_current_scene`, `list_scenes`, `switch_scene`), characters
(`list_characters`, `get_character`), tokens (`get_token_details`,
`move_token`, `toggle_token_condition`, `get_available_conditions`), rolls
(`request_player_rolls`), compendium (`search_compendium`,
`create_actor_from_compendium`), WFRP actor editing (`wfrp4e_update_actor`,
`wfrp4e_add_items`) and journals (`list_journals`, `search_journals`).

Tool schemas are cached in `games/wfrp/foundry_tools.json` so importing the
module never spawns a subprocess. Refresh after upgrading the bridge:

```bash
python -m games.wfrp.foundry --refresh
```

## Relationship to the offline rules database

The bridge complements the existing WFRP tooling rather than replacing it. The
offline database still answers rules and lore questions faster than a
compendium round-trip and keeps working when Foundry is closed. Foundry owns
board state and dice mechanics.
