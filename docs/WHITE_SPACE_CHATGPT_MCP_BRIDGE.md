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

## V1 tool surface

- `bridge_contract`: fixed authority model
- `runtime_health`: live health read
- `system_state`: canonical state read + SHA-256 observation hash
- `queue_status`: live queue read
- `capabilities`: live capability read
- `propose_action`: creates an unapproved, non-executing proposal

There is intentionally no MCP tool for approval or direct execution in V1.

## Drift controls

1. Read-before-propose.
2. Canonical state stays on WHITE_SPACE.
3. Every proposal carries an observation hash.
4. No model-side approval.
5. No model-side execution.
6. Fixed tool schemas and bounded endpoints.
7. Fail closed on API errors.
8. Keep secrets and private formulas local.

## PC-side requirement

The proposal endpoint should reject execution and keep a proposal pending until a separate local human-approval mechanism confirms it. The PC runtime should compare the proposal's `observed_state_sha256` or an equivalent revision token against current state before executing.

## Connectivity

The MCP server should remain private. For ChatGPT access to a private/local MCP server, use Secure MCP Tunnel rather than exposing the WHITE_SPACE API directly.

The ChatGPT-facing MCP endpoint and the WHITE_SPACE internal API are separate trust boundaries.
