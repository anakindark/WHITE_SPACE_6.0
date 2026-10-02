# WHITE_SPACE Automatic Operator Loop

## Purpose

This loop lets ChatGPT and the local WHITE_SPACE machine exchange bounded tasks and receipts without the owner manually copying messages between them.

```text
ChatGPT / connected GitHub tool
  -> structured WS_TASK_V1 comment on pinned issue
  -> local operator polls GitHub outbound-only
  -> built-in allowlisted action handler
  -> WHITE_SPACE / MCP bridge / PC runtime
  -> structured WS_RECEIPT_V1 comment
  -> ChatGPT monitor reads receipt and advances or reports
```

GitHub is the asynchronous control plane. It stores only sanitized task metadata and receipts. Secrets, private formulas, raw datasets, local credentials, and runtime internals remain local.

## Why this method

- No inbound port is opened on the PC or Mac.
- No self-hosted GitHub runner is attached to a public repository.
- Issue text cannot become arbitrary shell code.
- The local operator accepts tasks only from pinned GitHub authors.
- Only compiled-in action names are allowed.
- Each task has an ID, target host, issue time, expiry time, and optional required commit.
- Every result is returned as a structured receipt.

## Current built-in actions

- `deploy_chatgpt_desktop_bridge`
- `verify_white_space_bridge`

Both route to a fixed repository action handler. Parameters named `command`, `shell`, `script`, `powershell`, `bash`, or `cmd` are rejected.

## One-time local bootstrap

### Windows

```powershell
cd <WHITE_SPACE_6.0 repository>
.\local_operator\install_windows.ps1
```

The installer:

1. verifies Python and authenticated GitHub CLI,
2. creates a local configuration if absent,
3. registers a user-level scheduled task at logon,
4. starts the operator immediately,
5. stores local logs under `%USERPROFILE%\.white_space\operator`.

### macOS

```bash
cd <WHITE_SPACE_6.0 repository>
chmod +x local_operator/install_mac.sh
./local_operator/install_mac.sh
```

The installer creates a user LaunchAgent and starts it immediately. Logs stay under `~/.white_space/operator`.

## Authentication

The operator uses `GITHUB_TOKEN` when present. Otherwise it uses the token already held by authenticated GitHub CLI:

```bash
gh auth status
```

No token is written to GitHub comments or repository files.

## Task packet

A valid command is a GitHub issue comment containing:

```text
<!-- WS_TASK_V1 -->
```json
{
  "schema": "WS_TASK_V1",
  "task_id": "ws-bridge-deploy-001",
  "action": "deploy_chatgpt_desktop_bridge",
  "target_host": "PC_BIRD",
  "issued_at": "2026-10-03T03:00:00+07:00",
  "expires_at": "2026-10-04T03:00:00+07:00",
  "required_main_commit": "<commit>",
  "parameters": {
    "restart_test": true
  }
}
```
```

The operator ignores ordinary prose. It never treats issue text as a shell command.

## Receipt packet

The local operator posts ACK and FINAL receipts:

```text
<!-- WS_RECEIPT_V1 -->
```json
{
  "schema": "WS_RECEIPT_V1",
  "task_id": "ws-bridge-deploy-001",
  "host_id": "PC_BIRD",
  "phase": "FINAL",
  "status": "PASS",
  "details": {}
}
```
```

## Bridge deployment behavior

The built-in deployment action:

1. rejects a dirty repository,
2. fetches `origin/main` and verifies the required commit,
3. checks Node.js 20+ and npm,
4. uses an explicit API base or safely probes local `127.0.0.1:8820`,
5. discovers read endpoints from OpenAPI or uses an explicit endpoint map,
6. verifies every read endpoint before writing bridge configuration,
7. keeps the MCP server on `127.0.0.1`,
8. keeps proposal/write mode disabled,
9. runs bridge syntax and integration tests,
10. starts the bridge and verifies all required MCP read tools,
11. performs a restart verification when it owns the launched process,
12. reports the state hash and sanitized outcome.

It does not install secrets, change firewalls, approve actions, execute broker/trading actions, or expose the WHITE_SPACE API publicly.

## Authority

```text
ChatGPT         = non-canonical controller
GitHub issue    = bounded asynchronous queue
Local operator  = guarded dispatcher
WHITE_SPACE API = source of truth
PC runtime      = canonical executor
Human           = final authority
```

This makes the systems communicate automatically while preserving the existing governance model.
