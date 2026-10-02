# WHITE_SPACE ChatGPT MCP Bridge

This bridge implements the authority split:

- Chat = non-canonical controller
- WHITE_SPACE API = source of truth
- PC runtime = canonical executor
- MCP tools = contract
- Human final = authority

## Safety model

The MCP server exposes live read tools and one proposal tool. It intentionally exposes **no approve tool and no execute tool**.

Every `propose_action` call first reads the current WHITE_SPACE state, hashes that observation, and sends the proposal with:

- `requires_human_approval: true`
- `approved: false`
- `execute: false`
- `observed_state_sha256`

This prevents the ChatGPT conversation from becoming canonical state and makes stale-context detection possible on the PC side.

## Install

Node.js 20+ is required.

```bash
cd mcp_bridge
npm install
cp .env.example .env
```

Set the WHITE_SPACE endpoint paths to match the actual PC API. Do not commit credentials.

Start the bridge:

```bash
set -a
. ./.env
set +a
npm start
```

On Windows PowerShell, set the environment variables in the shell or service configuration before running `npm start`.

The default local MCP endpoint is:

```text
http://127.0.0.1:8787/mcp
```

## Test

```bash
npm run check
npx @modelcontextprotocol/inspector@latest
```

Use Streamable HTTP in MCP Inspector and connect to `http://127.0.0.1:8787/mcp`.

Recommended call sequence:

1. `bridge_contract`
2. `runtime_health`
3. `system_state`
4. `queue_status` or `capabilities`
5. `propose_action` only after the live state has been inspected

## ChatGPT connection

Keep the server bound to loopback. Use OpenAI Secure MCP Tunnel for a local/private server rather than opening the WHITE_SPACE API to the public internet.

After the tunnel is connected, attach the MCP app/plugin in ChatGPT and scan its tools.

## Required WHITE_SPACE API contract

The bridge expects JSON responses from the configured read paths. The proposal endpoint must accept a JSON POST containing the proposal object.

The actual endpoint names are configurable because the canonical PC API remains authoritative. No endpoint shape is inferred from chat history.

## Fail-closed rule

If a configured WHITE_SPACE path is missing, blocked, times out, or returns a non-2xx response, the MCP tool fails. It does not substitute remembered state or attempt a different endpoint.
