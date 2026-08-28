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
| Connection Type | `auto` |
| Auto-reconnect | enabled |
| Websocket Server Host | an address for the Pi that the **browser** can reach |

That host is resolved by the GM's browser, not by the Foundry server, and the
setting is world-scoped so it applies to every client. Verify it before
trusting it:

```bash
curl -s -o /dev/null -w '%{http_code}\n' http://<host>:31415/foundry-mcp
```

`404` means the port is reachable (the endpoint requires a WebSocket upgrade);
a timeout means the browser will not get through either.

Note the direction of travel: the **browser opens a connection into the Pi**.
Anything that permits the Pi's outbound traffic but blocks inbound traffic to it
— wireless client isolation, a guest SSID, a host firewall — breaks the bridge
while leaving the Pi apparently "on the network". Test with `nc -z <host> 22`
first; if plain SSH to that address fails, the bridge will fail too, and the
problem is the network rather than the module.

The characteristic signature of a blocked inbound path is a half-open handshake.
Run this on the Pi while the browser is trying to connect:

```bash
ss -tn state all | grep 31415
```

The three outcomes mean very different things:

| What `ss` shows | Meaning |
| --- | --- |
| `ESTAB` | Working. |
| `SYN-RECV` | The browser's SYN arrived and the Pi answered, but the final ACK never came back — the return path is blocked. Looks like a module fault and is not one. |
| `LISTEN` only, no peer | The browser is not dialling at all. The network is fine; the module has given up or is misconfigured. |

That last case is the easy one to misread, because everything on the Pi looks
healthy. Confirm the port really is reachable from the machine running the
browser before touching anything else:

```bash
nc -z omega7.panther-firefighter.ts.net 31415
```

If that succeeds while nothing reaches 31415, the fault is in the module's saved
settings. They can be read straight out of the world's LevelDB without stopping
Foundry, by copying the store and dropping the `LOCK` (read-only — Foundry
overwrites the live values on shutdown, so never write here):

```bash
W=/mnt/user/data/Foundry/Data/worlds/<world>/data/settings
rm -rf /tmp/setread && mkdir -p /tmp/setread
cp -r "$W" /tmp/setread/settings && rm -f /tmp/setread/settings/LOCK

docker run --rm -v /tmp/setread:/work \
  -v /mnt/user/appdata/FoundryVTT/resources/app/node_modules:/nm:ro \
  -e NODE_PATH=/nm -w /work node:24-alpine node -e '
const {ClassicLevel}=require("classic-level");
(async()=>{const db=new ClassicLevel("/work/settings",{valueEncoding:"json"});
for await (const [k,v] of db.iterator()){const key=(v&&v.key)?v.key:String(k);
if(/foundry-mcp-bridge/.test(key)) console.log(key,"=",JSON.stringify(v.value));}
await db.close();})();'
```

Note the setting name lives in the *value* (`v.key`), not the LevelDB key, so
filtering on the raw key returns nothing. Check `serverHost`,
`autoReconnectEnabled`, and `lastConnectionState`.

With auto-reconnect disabled, the module only retries **5 times, 1 second
apart**, after the world loads. If Omega-7 was not running at that moment,
reload the browser tab — it is almost always the explanation for a bridge that
"won't connect". Leaving auto-reconnect enabled avoids this, at the cost of the
backoff described below.

`autoReconnectEnabled` has been observed reverting to `false` on its own after a
failed session, leaving `lastConnectionState: "error"`. The module then never
dials again and the Pi sits at `LISTEN` forever. Re-enable it in **Game Settings
→ Configure Settings → MCP Bridge**; because the Pi only holds 31415 open while
an MCP client is attached, hold a listener open while reconnecting:

```bash
PYTHONPATH=$HOME/Servoskull .venv/bin/python -u -c '
import time
from games.wfrp import foundry
for i in range(200): foundry.status(); time.sleep(3)'
```

Because the server is spawned per MCP client and torn down when that client
exits, the module loses its socket every time a short-lived process (a test
script, a one-off `python -c`) finishes. With auto-reconnect on, repeated
teardowns push the module into exponential backoff, and a subsequent connection
can take **up to two minutes**. This is invisible in normal use — the long-lived
Omega-7 service starts the node process once and the module stays attached — but
it makes short-lived scripts a poor way to test the bridge. Reloading the
Foundry tab resets the backoff immediately.

Note that the backend only binds ports **after** an MCP client completes the
stdio handshake, so `ss -lntp | grep 31415` shows nothing until Omega-7 has
actually called it once.

### This deployment

Omega-7's Pi lives inside the skull prop, so **ethernet is not an option** —
`eth0` stays down and it is on `wlan0` permanently. The house AP has client
isolation enabled, which blocks traffic between wireless clients. The practical
consequences:

| From the GM's machine | Result |
| :--- | :--- |
| `192.168.0.108` (the Pi's LAN address) | blocked — stalls in `SYN-RECV` |
| `omega7.local` | unreliable — resolves to IPv4 for browsers and is blocked, even though a shell may reach it over IPv6 link-local |
| `omega7.panther-firefighter.ts.net` (Tailscale) | works |

**Tailscale is therefore a hard requirement, not a convenience.** Any machine
running the GM browser must be on the tailnet, and the Server Host must be the
Tailscale name above. The raw Tailscale IP works too but is not stable across
re-registration, so prefer the MagicDNS name.

The same isolation blocks Omega-7's web app on port 8080, which additionally
binds IPv4-only. Reach it over Tailscale as well.

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
