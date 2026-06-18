# Codex + GitHub Bridge

This repository is the coordination layer. The Codex desktop room on the MacBook remains the private runtime.

## What GitHub Should Do

- Track operator tasks as issues.
- Run public bridge safety CI.
- Store sanitized evidence and replay manifests.
- Host non-secret dashboards or docs.

## What GitHub Must Not Do

- Store private TFEX formula code/constants.
- Store raw private datasets.
- Store broker credentials or API keys.
- Execute live trades.
- Treat agent consensus as human approval.

## Recommended Workflow

1. GitHub issue defines task and privacy tier.
2. Codex pulls task into local runtime.
3. Codex executes local proof or paper workflow.
4. Codex writes sanitized summary back only if permitted.
5. Human approves any external write, paid provider, broker, or destructive action.

## Level Framing

This is a bounded controlled operator bridge. It can raise system capability by adding tools, CI, audit trail, and persistence. It does not increase raw model intelligence and does not prove public AGI.
