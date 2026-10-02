# WHITE_SPACE Desktop Plugin

This is the shortest private path for a normal ChatGPT conversation on a computer:

```text
ChatGPT Desktop
  -> local WHITE_SPACE plugin
  -> http://127.0.0.1:8787/mcp
  -> guarded MCP bridge
  -> WHITE_SPACE API
  -> PC runtime / RTX / cache
```

The plugin package is at `plugins/white-space-controller`.

## Why use the desktop-local path

OpenAI currently supports plugins that include local MCP apps on ChatGPT Desktop. Local tools saved with such a plugin do not become available on web or mobile.

This path therefore avoids publishing the WHITE_SPACE API and does not require Secure MCP Tunnel merely to use the plugin from ChatGPT Desktop on the same computer that can reach the bridge.

## Mac setup

From the repository:

```bash
cd mcp_bridge
./run_local_mac.sh
```

On first run it creates `.env` and stops. Set the actual WHITE_SPACE API URL and allowed host, then run it again.

Example only for a PC reachable over a private LAN:

```text
WS_API_BASE=http://<PC-private-address>:8820
WS_ALLOWED_API_HOSTS=<PC-private-address>
```

Do not copy a remembered address from chat. Read the live address from the actual machine/network.

## Windows setup

```powershell
cd mcp_bridge
.\run_local_windows.ps1
```

The same fail-closed environment contract applies.

## Plugin installation

Use ChatGPT Desktop and Plugin Creator/local plugin tooling to add the folder:

```text
plugins/white-space-controller
```

The bundled MCP URL is loopback-only:

```text
http://127.0.0.1:8787/mcp
```

The MCP bridge must already be running.

## Mobile and web

A local MCP plugin does not make its local tools available on web or mobile. For web access to a private MCP server, use a supported remote/private connection such as Secure MCP Tunnel. Mobile MCP apps are currently unsupported.

## Authority remains unchanged

- ChatGPT = non-canonical controller
- WHITE_SPACE API = source of truth
- PC runtime = canonical executor
- MCP tools = contract
- Human = final authority
