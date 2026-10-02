#!/usr/bin/env python3
"""Public GitHub bridge safety check."""

from __future__ import annotations

import json
from pathlib import Path


PRIVATE_MARKERS = [
    "KH" + "_PCT" + "_98C",
    "KL" + "_PCT" + "_98C",
    "KU" + "_SMALL",
    "KD" + "_SMALL",
    "KU" + "_BIG",
    "KD" + "_BIG",
    "CANONICAL" + "_HASH" + "_98C",
    "WHITE_SPACE" + "_100S" + "_98C",
    "S50M26" + "_2026",
    "SET50" + "Futures",
    "broker" + "_password",
    "api" + "_key",
    "OPENAI" + "_API" + "_KEY",
]
ROOT = Path(__file__).resolve().parents[1]
ALLOWLIST = {
    ".github/workflows/white-space-operator-bridge.yml",
    ".github/ISSUE_TEMPLATE/white-space-operator-task.yml",
    ".github/pull_request_template.md",
    "docs/WHITE_SPACE_CODEX_GITHUB_BRIDGE.md",
    "docs/WHITE_SPACE_CHATGPT_MCP_BRIDGE.md",
    "docs/WHITE_SPACE_DESKTOP_PLUGIN.md",
    "mcp_bridge/.env.example",
    "mcp_bridge/README.md",
    "mcp_bridge/package.json",
    "mcp_bridge/server.js",
    "mcp_bridge/test/integration.test.js",
    "mcp_bridge/run_local_mac.sh",
    "mcp_bridge/run_local_windows.ps1",
    "plugins/white-space-controller/plugin.json",
    "plugins/white-space-controller/mcp.json",
    "plugins/white-space-controller/skills/white-space-live-state/SKILL.md",
    "scripts/white_space_public_ci_check.py",
    "white_space_operator_bridge_manifest.json",
    "README.md",
}


def main() -> int:
    failures = []
    manifest_path = ROOT / "white_space_operator_bridge_manifest.json"
    if not manifest_path.exists():
        failures.append("missing manifest")
    else:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        gates = manifest.get("default_gates", {})
        for key in [
            "human_final_authority",
            "no_secret_upload",
            "no_private_formula_upload",
            "no_broker_execution",
            "no_direct_mcp_execution",
        ]:
            if gates.get(key) is not True:
                failures.append(f"gate not true: {key}")

    for rel in sorted(ALLOWLIST):
        path = ROOT / rel
        if not path.exists():
            failures.append(f"missing allowlisted file: {rel}")
            continue
        text = path.read_text(encoding="utf-8", errors="ignore")
        for marker in PRIVATE_MARKERS:
            if marker in text:
                failures.append(f"private marker found in {rel}: {marker}")

    for rel in [
        "plugins/white-space-controller/plugin.json",
        "plugins/white-space-controller/mcp.json",
    ]:
        path = ROOT / rel
        try:
            json.loads(path.read_text(encoding="utf-8"))
        except Exception as exc:
            failures.append(f"invalid plugin JSON in {rel}: {exc}")

    report = {
        "status": "PASS" if not failures else "FAIL",
        "failures": failures,
        "checked_files": sorted(ALLOWLIST),
    }
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0 if not failures else 1


if __name__ == "__main__":
    raise SystemExit(main())
