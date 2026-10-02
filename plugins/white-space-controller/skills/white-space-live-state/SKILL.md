---
name: white-space-live-state
description: Read and interpret live WHITE_SPACE state using the local MCP bridge while preserving canonical authority boundaries.
---

Use the WHITE_SPACE MCP tools for any claim about current runtime state.

Rules:

1. Treat ChatGPT conversation context as non-canonical.
2. Read `bridge_contract` before the first WHITE_SPACE control task in a new session.
3. Use `runtime_health`, `system_state`, `queue_status`, or `capabilities` for current facts.
4. If a live read fails, report the failure. Do not substitute remembered state.
5. Do not claim that an action executed unless the canonical PC runtime reports execution.
6. Do not approve or execute actions from chat.
7. Human final authority remains required for any external write, destructive action, paid-provider action, or broker/trading action.
8. Keep private formulas, credentials, and raw private datasets local.
