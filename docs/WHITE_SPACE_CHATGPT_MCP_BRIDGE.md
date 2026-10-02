# WHITE_SPACE ChatGPT MCP Bridge

## Authority

```text
ChatGPT            = non-canonical controller
WHITE_SPACE API    = source of truth
PC runtime         = canonical executor
MCP tools          = contract
Human              = final authority
```

## Data flow

```text
User
  |
  v
ChatGPT
  |
  | MCP tool call
  v
WHITE_SPACE MCP bridge
  |
  | bounded HTTP contract
  v
WHITE_SPACE API
  |
  v
PC runtime / local tools / RTX / cache
```

The bridge never treats chat memory as live system state. Read tools request the current PC-side state every time.

## Tool surface

Always present:

- `bridge_contract`
- `runtime_health`
- `system_state`
- `queue_status`
- `capabilities`

Optional, disabled by default:

- `propose_action` — creates an unapproved, non-executing proposal only

There is intentionally no MCP tool for approval or direct execution.

## Drift controls

1. Canonical state stays on WHITE_SPACE.
2. Live reads never fall back to chat memory.
3. Proposal mode performs read-before-propose.
4. Proposal mode carries a stable state SHA-256 observation hash.
5. No model-side approval.
6. No model-side execution.
7. Fixed endpoint allowlist.
8. Fixed tool schemas.
9. Bounded response size and timeout.
10. HTTP redirects rejected.
11. Fail closed on API errors.
12. Keep secrets and private formulas local.

## PC-side requirement

The live PC runtime must provide the exact endpoint contract configured in `mcp_bridge/.env`.

If proposal mode is ever enabled, the proposal endpoint must keep every proposal pending until a separate local human-approval mechanism confirms it. The PC runtime should also compare the proposal observation hash or a stronger canonical revision token against current state before execution.

## Connectivity

The MCP server remains on loopback. ChatGPT reaches a private/local MCP server through Secure MCP Tunnel rather than by exposing WHITE_SPACE directly to the public internet.

The ChatGPT-facing MCP endpoint and the WHITE_SPACE internal API are separate trust boundaries.

## Current ChatGPT availability

As of 2026-10-03, OpenAI documents full MCP write/modify support as a Business and Enterprise/Edu beta. Pro users can connect custom MCPs with read/fetch permissions in developer mode. MCP apps are currently web-only.

Therefore the production default is read-only. The proposal tool remains opt-in for a workspace that supports MCP write actions.
