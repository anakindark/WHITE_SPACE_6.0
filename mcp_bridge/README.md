# WHITE_SPACE ChatGPT MCP Bridge

This bridge implements the authority split:

- ChatGPT = non-canonical controller
- WHITE_SPACE API = source of truth
- PC runtime = canonical executor
- MCP tools = contract
- Human final = authority

## Current status

The bridge is designed for the current MCP TypeScript SDK v2 and the 2026-07-28 MCP protocol generation.

It is **read-only by default**. The optional `propose_action` tool is not registered unless `WS_ENABLE_PROPOSALS=true`.

There is deliberately no MCP approval tool and no MCP execute tool.

## Safety model

Every live read comes from the configured WHITE_SPACE API. If that API is unreachable, slow, returns a non-2xx status, exceeds the response-size limit, or returns through an unapproved hostname, the tool fails closed. The bridge never substitutes remembered ChatGPT state.

When proposals are enabled, `propose_action`:

1. re-reads canonical state,
2. computes a stable SHA-256 observation hash,
3. creates a proposal with `requires_human_approval=true`,
4. sets `approved=false`,
5. sets `execute=false`.

The PC runtime must keep the proposal pending until a separate local human approval succeeds.

## Install

Node.js 20+ is required.

```bash
cd mcp_bridge
npm install
cp .env.example .env
```

Set the WHITE_SPACE endpoint paths to the actual API contract. Do not commit credentials.

If the bridge runs on a Mac while WHITE_SPACE runs on a PC, add the exact PC LAN/VPN hostname or IP to `WS_ALLOWED_API_HOSTS`. The bridge rejects non-allowlisted API hosts.

Start:

```bash
set -a
. ./.env
set +a
npm start
```

Default local endpoint:

```text
http://127.0.0.1:8787/mcp
```

## Test

```bash
npm run check
npm test
```

The integration test starts a mock WHITE_SPACE API, connects with an MCP v2 client, verifies the read tools, verifies fail-closed behavior, and verifies that an enabled proposal is always emitted as unapproved and non-executing.

For manual testing:

```bash
npx @modelcontextprotocol/inspector@latest
```

Connect with Streamable HTTP to `http://127.0.0.1:8787/mcp`.

## ChatGPT connection

ChatGPT does not connect directly to a localhost MCP endpoint. Keep this server bound to loopback and use OpenAI Secure MCP Tunnel for a private/on-premises server rather than publishing the WHITE_SPACE API.

Current OpenAI product availability is plan-dependent. Full MCP write/modify actions are currently available in Business and Enterprise/Edu beta. Pro can connect custom MCPs with read/fetch permissions in developer mode. MCP apps are currently web-only, not mobile.

That means the default read-only bridge is the compatible path for a Pro account today. `propose_action` should remain disabled unless the connected ChatGPT workspace supports write actions.

## Required WHITE_SPACE API contract

The configured read endpoints must return JSON.

The optional proposal endpoint must accept a JSON POST containing the proposal object and must not interpret receipt of a proposal as approval.

Endpoint names are configurable because the PC runtime remains canonical. No endpoint path is inferred from chat history.

## Fail-closed rule

If the canonical API contract is not known, do not guess it. Set the exact paths in `.env` after checking the live PC runtime.
