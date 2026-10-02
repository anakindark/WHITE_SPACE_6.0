#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
OP_DIR="$ROOT/local_operator"
CONFIG="$OP_DIR/operator_config.json"
STATE_DIR="$HOME/.white_space/operator"
PLIST="$HOME/Library/LaunchAgents/com.whitespace.local-operator.plist"
PYTHON="$(command -v python3 || true)"
GH="$(command -v gh || true)"

if [[ -z "$PYTHON" ]]; then
  echo "Python 3 is required." >&2
  exit 1
fi
if [[ -z "$GH" ]]; then
  echo "GitHub CLI (gh) is required." >&2
  exit 1
fi
"$GH" auth status >/dev/null

mkdir -p "$STATE_DIR" "$HOME/Library/LaunchAgents"

if [[ ! -f "$CONFIG" ]]; then
  HOST_ID="$(hostname -s 2>/dev/null || hostname)"
  cat >"$CONFIG" <<JSON
{
  "repository": "anakindark/WHITE_SPACE_6.0",
  "issue_number": 4,
  "allowed_authors": ["anakindark"],
  "host_id": "$HOST_ID",
  "poll_seconds": 30,
  "state_dir": "$STATE_DIR"
}
JSON
  chmod 600 "$CONFIG"
fi

cat >"$PLIST" <<PLIST
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key>
  <string>com.whitespace.local-operator</string>
  <key>ProgramArguments</key>
  <array>
    <string>$PYTHON</string>
    <string>-u</string>
    <string>$OP_DIR/ws_local_operator.py</string>
    <string>--config</string>
    <string>$CONFIG</string>
  </array>
  <key>WorkingDirectory</key>
  <string>$ROOT</string>
  <key>RunAtLoad</key>
  <true/>
  <key>KeepAlive</key>
  <true/>
  <key>ThrottleInterval</key>
  <integer>10</integer>
  <key>StandardOutPath</key>
  <string>$STATE_DIR/operator.stdout.log</string>
  <key>StandardErrorPath</key>
  <string>$STATE_DIR/operator.stderr.log</string>
</dict>
</plist>
PLIST

launchctl bootout "gui/$(id -u)" "$PLIST" >/dev/null 2>&1 || true
launchctl bootstrap "gui/$(id -u)" "$PLIST"
launchctl enable "gui/$(id -u)/com.whitespace.local-operator"
launchctl kickstart -k "gui/$(id -u)/com.whitespace.local-operator"

echo "WHITE_SPACE local operator installed and started."
echo "Config: $CONFIG"
echo "Logs: $STATE_DIR"
