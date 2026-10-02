#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "$0")" && pwd)"
cd "$ROOT"

if ! command -v node >/dev/null 2>&1; then
  echo "Node.js 20+ is required." >&2
  exit 1
fi

NODE_MAJOR="$(node -p 'process.versions.node.split(".")[0]')"
if [ "$NODE_MAJOR" -lt 20 ]; then
  echo "Node.js 20+ is required; found $(node -v)." >&2
  exit 1
fi

if [ ! -f .env ]; then
  cp .env.example .env
  echo "Created mcp_bridge/.env. Edit WS_API_BASE and WS_ALLOWED_API_HOSTS to match the live WHITE_SPACE API, then rerun." >&2
  exit 2
fi

set -a
. ./.env
set +a

npm install --ignore-scripts
npm run check
npm test
exec npm start
