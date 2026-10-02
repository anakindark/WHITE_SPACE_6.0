#!/usr/bin/env python3
"""Built-in deployment/verification action for the guarded local operator.

This script accepts declarative task parameters only. It does not execute shell
text from GitHub. It probes localhost or an explicitly supplied API base,
discovers read endpoints from OpenAPI when possible, writes a bounded bridge
configuration, runs tests, starts the loopback MCP bridge, and verifies live
read tools.
"""

from __future__ import annotations

import argparse
import json
import os
import pathlib
import re
import shutil
import signal
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from typing import Any


class DeployError(RuntimeError):
    pass


def run(
    args: list[str],
    *,
    cwd: pathlib.Path,
    timeout: int = 300,
    check: bool = True,
    env: dict[str, str] | None = None,
) -> subprocess.CompletedProcess[str]:
    result = subprocess.run(
        args,
        cwd=cwd,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        timeout=timeout,
        env=env,
    )
    if check and result.returncode != 0:
        raise DeployError(
            f"command failed ({result.returncode}): {' '.join(args)}\n"
            f"stdout: {result.stdout[-3000:]}\n"
            f"stderr: {result.stderr[-3000:]}"
        )
    return result


def read_env(path: pathlib.Path) -> dict[str, str]:
    values: dict[str, str] = {}
    if not path.exists():
        return values
    for raw in path.read_text(encoding="utf-8", errors="replace").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        values[key.strip()] = value.strip()
    return values


def safe_path(value: str, name: str) -> str:
    if (
        not value.startswith("/")
        or value.startswith("//")
        or ".." in value
        or "?" in value
        or "#" in value
    ):
        raise DeployError(f"invalid {name}: {value!r}")
    return value


def get_json(
    url: str,
    *,
    token: str = "",
    timeout: float = 5.0,
    allow_non_json: bool = False,
) -> tuple[int, Any]:
    headers = {"Accept": "application/json", "User-Agent": "white-space-local-deployer/1.0"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    request = urllib.request.Request(url, headers=headers, method="GET")
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            raw = response.read(2 * 1024 * 1024 + 1)
            if len(raw) > 2 * 1024 * 1024:
                raise DeployError(f"response too large from {url}")
            text = raw.decode("utf-8", errors="replace")
            try:
                return response.status, json.loads(text) if text else {}
            except json.JSONDecodeError:
                if allow_non_json:
                    return response.status, {"raw": text[:2000]}
                raise DeployError(f"non-JSON response from {url}")
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")[:1000]
        raise DeployError(f"HTTP {exc.code} from {url}: {detail}") from exc
    except urllib.error.URLError as exc:
        raise DeployError(f"cannot reach {url}: {exc.reason}") from exc


def base_url(value: str) -> str:
    parsed = urllib.parse.urlparse(value)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise DeployError(f"invalid API base URL: {value!r}")
    if parsed.username or parsed.password or parsed.query or parsed.fragment:
        raise DeployError("API base URL must not contain credentials, query, or fragment")
    return value.rstrip("/")


def score_endpoint(kind: str, path: str, operation: dict[str, Any]) -> int:
    haystack = " ".join(
        [
            path.lower(),
            str(operation.get("operationId", "")).lower(),
            str(operation.get("summary", "")).lower(),
            str(operation.get("description", "")).lower(),
            " ".join(str(v).lower() for v in operation.get("tags", []) if isinstance(v, str)),
        ]
    )
    basename = path.rstrip("/").split("/")[-1].lower()
    keywords = {
        "health": ["health", "liveness", "readiness", "ready", "ping"],
        "state": ["system state", "runtime state", "canonical state", "state"],
        "queue": ["queue", "work queue", "task queue"],
        "capabilities": ["capabilities", "capability", "features"],
    }[kind]
    score = 0
    for keyword in keywords:
        if keyword in haystack:
            score += 20 if keyword in path.lower() else 8
    exact = {
        "health": {"health", "ping", "ready", "readiness", "liveness"},
        "state": {"state", "system-state", "runtime-state"},
        "queue": {"queue", "queue-status"},
        "capabilities": {"capabilities", "capability"},
    }[kind]
    if basename in exact:
        score += 50
    if any(part in path.lower() for part in ["delete", "write", "update", "execute", "admin"]):
        score -= 100
    return score


def discover_endpoints(api: str, token: str, explicit: dict[str, Any] | None) -> dict[str, str]:
    if explicit:
        required = {
            "health": "WS_HEALTH_PATH",
            "state": "WS_STATE_PATH",
            "queue": "WS_QUEUE_PATH",
            "capabilities": "WS_CAPABILITIES_PATH",
        }
        found: dict[str, str] = {}
        for key in required:
            if key not in explicit:
                raise DeployError(f"endpoint_map missing {key}")
            found[key] = safe_path(str(explicit[key]), key)
        return found

    _, spec = get_json(f"{api}/openapi.json", token=token, timeout=7)
    paths = spec.get("paths") if isinstance(spec, dict) else None
    if not isinstance(paths, dict):
        raise DeployError("OpenAPI discovery unavailable; supply parameters.endpoint_map explicitly")

    selected: dict[str, str] = {}
    for kind in ["health", "state", "queue", "capabilities"]:
        ranked: list[tuple[int, str]] = []
        for path, methods in paths.items():
            if not isinstance(path, str) or not isinstance(methods, dict):
                continue
            operation = methods.get("get")
            if not isinstance(operation, dict):
                continue
            score = score_endpoint(kind, path, operation)
            if score > 0:
                ranked.append((score, path))
        ranked.sort(key=lambda item: (-item[0], len(item[1]), item[1]))
        if not ranked or ranked[0][0] < 20:
            raise DeployError(f"could not safely discover {kind} endpoint from OpenAPI")
        selected[kind] = safe_path(ranked[0][1], kind)

    if len(set(selected.values())) < 3:
        raise DeployError(f"endpoint discovery is ambiguous: {selected}")
    return selected


def verify_api_paths(api: str, endpoints: dict[str, str], token: str) -> dict[str, Any]:
    observations: dict[str, Any] = {}
    for kind, path in endpoints.items():
        status, data = get_json(f"{api}{path}", token=token, timeout=10)
        if status < 200 or status >= 300:
            raise DeployError(f"{kind} endpoint returned HTTP {status}")
        observations[kind] = {
            "path": path,
            "response_type": type(data).__name__,
        }
    return observations


def write_bridge_env(
    env_path: pathlib.Path,
    *,
    api: str,
    endpoints: dict[str, str],
    bearer_token: str,
) -> None:
    parsed = urllib.parse.urlparse(api)
    hostname = parsed.hostname or ""
    if not hostname:
        raise DeployError("API base has no hostname")
    lines = [
        "# Generated by WHITE_SPACE guarded local operator.",
        "HOST=127.0.0.1",
        "PORT=8787",
        "MCP_PATH=/mcp",
        f"WS_API_BASE={api}",
        f"WS_HEALTH_PATH={endpoints['health']}",
        f"WS_STATE_PATH={endpoints['state']}",
        f"WS_QUEUE_PATH={endpoints['queue']}",
        f"WS_CAPABILITIES_PATH={endpoints['capabilities']}",
        "WS_PROPOSAL_PATH=/proposals",
        "WS_TIMEOUT_MS=5000",
        "WS_MAX_RESPONSE_BYTES=1048576",
        f"WS_ALLOWED_API_HOSTS={hostname}",
        "WS_ENABLE_PROPOSALS=false",
        f"WS_BRIDGE_BEARER_TOKEN={bearer_token}",
        "",
    ]
    env_path.write_text("\n".join(lines), encoding="utf-8")
    try:
        os.chmod(env_path, 0o600)
    except OSError:
        pass


def wait_bridge(timeout: float = 30.0) -> dict[str, Any]:
    deadline = time.monotonic() + timeout
    last_error = ""
    while time.monotonic() < deadline:
        try:
            _, data = get_json("http://127.0.0.1:8787/", timeout=2)
            if isinstance(data, dict) and data.get("service") == "WHITE_SPACE MCP bridge":
                return data
            last_error = f"unexpected root response: {data}"
        except Exception as exc:
            last_error = str(exc)
        time.sleep(0.5)
    raise DeployError(f"MCP bridge did not become ready: {last_error}")


def terminate_process(process: subprocess.Popen[Any]) -> None:
    if process.poll() is not None:
        return
    try:
        process.terminate()
        process.wait(timeout=10)
    except Exception:
        try:
            process.kill()
        except Exception:
            pass


def start_bridge(bridge_dir: pathlib.Path, state_dir: pathlib.Path, env: dict[str, str]) -> subprocess.Popen[Any]:
    npm = shutil.which("npm.cmd" if os.name == "nt" else "npm") or shutil.which("npm")
    if not npm:
        raise DeployError("npm is not installed or not on PATH")
    state_dir.mkdir(parents=True, exist_ok=True)
    log_path = state_dir / "mcp_bridge.log"
    log_handle = open(log_path, "ab", buffering=0)
    kwargs: dict[str, Any] = {
        "cwd": bridge_dir,
        "env": env,
        "stdout": log_handle,
        "stderr": subprocess.STDOUT,
    }
    if os.name == "nt":
        kwargs["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.DETACHED_PROCESS
    else:
        kwargs["start_new_session"] = True
    process = subprocess.Popen([npm, "start"], **kwargs)
    (state_dir / "mcp_bridge.pid").write_text(str(process.pid), encoding="ascii")
    return process


def parse_env_for_process(path: pathlib.Path) -> dict[str, str]:
    return {**os.environ, **read_env(path)}


def check_repository(repo_root: pathlib.Path, required_commit: str) -> dict[str, str]:
    git = shutil.which("git")
    if not git:
        raise DeployError("git is not installed or not on PATH")
    status = run([git, "status", "--porcelain"], cwd=repo_root).stdout.strip()
    if status:
        raise DeployError("repository has local changes; refusing automatic deployment")
    run([git, "fetch", "origin", "main"], cwd=repo_root, timeout=180)
    branch = run([git, "branch", "--show-current"], cwd=repo_root).stdout.strip()
    if branch == "main":
        run([git, "pull", "--ff-only", "origin", "main"], cwd=repo_root, timeout=180)
    head = run([git, "rev-parse", "HEAD"], cwd=repo_root).stdout.strip()
    if required_commit:
        ancestor = run(
            [git, "merge-base", "--is-ancestor", required_commit, head],
            cwd=repo_root,
            check=False,
        )
        if ancestor.returncode != 0:
            raise DeployError(f"required commit {required_commit} is not present in HEAD {head}")
    return {"branch": branch, "head": head}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo-root", type=pathlib.Path, required=True)
    parser.add_argument("--task-json", required=True)
    parser.add_argument("--verify-only", action="store_true")
    args = parser.parse_args()

    task = json.loads(args.task_json)
    if not isinstance(task, dict):
        raise DeployError("task JSON must be an object")
    parameters = task.get("parameters") or {}
    if not isinstance(parameters, dict):
        raise DeployError("task parameters must be an object")

    repo_root = args.repo_root.resolve()
    bridge_dir = repo_root / "mcp_bridge"
    plugin_dir = repo_root / "plugins" / "white-space-controller"
    state_dir = pathlib.Path(
        os.path.expandvars(os.path.expanduser(os.environ.get("WS_OPERATOR_STATE_DIR", "~/.white_space/operator")))
    ).resolve()
    env_path = bridge_dir / ".env"

    result: dict[str, Any] = {
        "status": "BLOCKED",
        "action": task.get("action"),
        "host_id": os.environ.get("WS_OPERATOR_HOST_ID", "UNKNOWN"),
        "read_only": True,
        "direct_execution": False,
    }

    process: subprocess.Popen[Any] | None = None
    try:
        result["repository"] = check_repository(repo_root, str(task.get("required_main_commit", "")))

        npm = shutil.which("npm.cmd" if os.name == "nt" else "npm") or shutil.which("npm")
        node = shutil.which("node")
        if not npm or not node:
            raise DeployError("Node.js 20+ and npm are required")
        node_major = int(run([node, "-p", "process.versions.node.split('.')[0]"], cwd=bridge_dir).stdout.strip())
        if node_major < 20:
            raise DeployError(f"Node.js 20+ required; found major version {node_major}")

        existing_env = read_env(env_path)
        token = str(parameters.get("bridge_bearer_token") or existing_env.get("WS_BRIDGE_BEARER_TOKEN") or os.environ.get("WS_BRIDGE_BEARER_TOKEN", ""))
        candidates = []
        for value in [
            parameters.get("api_base"),
            os.environ.get("WS_API_BASE"),
            existing_env.get("WS_API_BASE"),
            "http://127.0.0.1:8820",
        ]:
            if value and str(value) not in candidates:
                candidates.append(str(value))

        api = ""
        candidate_errors: dict[str, str] = {}
        for value in candidates:
            try:
                candidate = base_url(value)
                get_json(f"{candidate}/", token=token, timeout=3, allow_non_json=True)
                api = candidate
                break
            except Exception as exc:
                candidate_errors[value] = str(exc)
        if not api:
            raise DeployError(f"no reachable WHITE_SPACE API base; candidates={candidate_errors}")

        endpoint_map = parameters.get("endpoint_map")
        if endpoint_map is not None and not isinstance(endpoint_map, dict):
            raise DeployError("parameters.endpoint_map must be an object")
        endpoints = discover_endpoints(api, token, endpoint_map)
        result["api_base"] = api
        result["endpoints"] = verify_api_paths(api, endpoints, token)

        if args.verify_only:
            if not env_path.exists():
                raise DeployError("bridge .env does not exist")
        else:
            write_bridge_env(env_path, api=api, endpoints=endpoints, bearer_token=token)
            run([npm, "install", "--ignore-scripts"], cwd=bridge_dir, timeout=600)
            run([npm, "run", "check"], cwd=bridge_dir, timeout=180)
            run([npm, "test"], cwd=bridge_dir, timeout=300)

        process_env = parse_env_for_process(env_path)
        try:
            root = wait_bridge(timeout=2)
            result["bridge_reused"] = True
            result["bridge_root"] = root
        except Exception:
            process = start_bridge(bridge_dir, state_dir, process_env)
            result["bridge_reused"] = False
            result["bridge_root"] = wait_bridge(timeout=30)

        verify = run([npm, "run", "verify:live"], cwd=bridge_dir, timeout=120, env=process_env)
        live = json.loads(verify.stdout)
        result["live_verification"] = live

        if process is not None and bool(parameters.get("restart_test", True)):
            first_hash = live.get("state_sha256")
            terminate_process(process)
            time.sleep(1)
            process = start_bridge(bridge_dir, state_dir, process_env)
            wait_bridge(timeout=30)
            verify2 = run([npm, "run", "verify:live"], cwd=bridge_dir, timeout=120, env=process_env)
            live2 = json.loads(verify2.stdout)
            result["restart_verification"] = live2
            result["restart_state_hash_consistent"] = first_hash == live2.get("state_sha256")

        if not (plugin_dir / "plugin.json").exists() or not (plugin_dir / "mcp.json").exists():
            raise DeployError("desktop plugin package is missing")
        result["plugin_package"] = {
            "status": "READY",
            "path": str(plugin_dir),
            "desktop_install_required": True,
        }
        result["status"] = "PASS"
        print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
        return 0
    except Exception as exc:
        result["error"] = str(exc)
        print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
