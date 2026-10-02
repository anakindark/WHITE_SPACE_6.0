#!/usr/bin/env python3
"""Guarded GitHub-backed local operator for WHITE_SPACE.

The operator polls one pinned GitHub issue for structured WS_TASK_V1 packets,
executes only built-in allowlisted handlers, and posts WS_RECEIPT_V1 comments.
It never executes shell text supplied by an issue comment.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import pathlib
import re
import socket
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from typing import Any

TASK_MARKER = "<!-- WS_TASK_V1 -->"
RECEIPT_MARKER = "<!-- WS_RECEIPT_V1 -->"
TASK_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{2,127}$")
ALLOWED_ACTIONS = {
    "deploy_chatgpt_desktop_bridge",
    "verify_white_space_bridge",
}


class OperatorError(RuntimeError):
    """Expected fail-closed operator error."""


@dataclass(frozen=True)
class Config:
    repository: str
    issue_number: int
    allowed_authors: frozenset[str]
    host_id: str
    poll_seconds: int
    state_dir: pathlib.Path
    repository_root: pathlib.Path


def utc_now() -> dt.datetime:
    return dt.datetime.now(dt.timezone.utc)


def iso_utc(value: dt.datetime | None = None) -> str:
    return (value or utc_now()).astimezone(dt.timezone.utc).isoformat().replace("+00:00", "Z")


def parse_iso(value: str) -> dt.datetime:
    parsed = dt.datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise OperatorError("task timestamp must include a timezone")
    return parsed.astimezone(dt.timezone.utc)


def load_json(path: pathlib.Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise OperatorError(f"missing config: {path}") from exc
    except json.JSONDecodeError as exc:
        raise OperatorError(f"invalid JSON in {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise OperatorError(f"expected object in {path}")
    return value


def load_config(path: pathlib.Path) -> Config:
    raw = load_json(path)
    repo = str(raw.get("repository", "")).strip()
    if not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", repo):
        raise OperatorError("repository must be owner/name")

    issue = int(raw.get("issue_number", 0))
    if issue <= 0:
        raise OperatorError("issue_number must be positive")

    authors = frozenset(str(v).strip() for v in raw.get("allowed_authors", []) if str(v).strip())
    if not authors:
        raise OperatorError("allowed_authors cannot be empty")

    host_id = str(raw.get("host_id") or socket.gethostname()).strip()
    if not host_id:
        raise OperatorError("host_id cannot be empty")

    poll_seconds = int(raw.get("poll_seconds", 30))
    if poll_seconds < 10 or poll_seconds > 3600:
        raise OperatorError("poll_seconds must be between 10 and 3600")

    state_dir = pathlib.Path(os.path.expandvars(os.path.expanduser(str(raw.get("state_dir", "~/.white_space/operator"))))).resolve()
    repo_root_raw = raw.get("repository_root") or pathlib.Path(__file__).resolve().parents[1]
    repo_root = pathlib.Path(os.path.expandvars(os.path.expanduser(str(repo_root_raw)))).resolve()

    return Config(
        repository=repo,
        issue_number=issue,
        allowed_authors=authors,
        host_id=host_id,
        poll_seconds=poll_seconds,
        state_dir=state_dir,
        repository_root=repo_root,
    )


def gh_token() -> str:
    env_token = os.environ.get("GITHUB_TOKEN", "").strip()
    if env_token:
        return env_token
    try:
        result = subprocess.run(
            ["gh", "auth", "token"],
            check=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            timeout=15,
        )
    except (FileNotFoundError, subprocess.CalledProcessError, subprocess.TimeoutExpired) as exc:
        raise OperatorError(
            "GitHub authentication unavailable. Install/authenticate GitHub CLI or set GITHUB_TOKEN."
        ) from exc
    token = result.stdout.strip()
    if not token:
        raise OperatorError("GitHub token is empty")
    return token


def github_request(token: str, method: str, url: str, payload: dict[str, Any] | None = None) -> Any:
    data = None if payload is None else json.dumps(payload).encode("utf-8")
    request = urllib.request.Request(
        url,
        data=data,
        method=method,
        headers={
            "Accept": "application/vnd.github+json",
            "Authorization": f"Bearer {token}",
            "X-GitHub-Api-Version": "2022-11-28",
            "User-Agent": "white-space-local-operator/1.0",
            **({"Content-Type": "application/json"} if data is not None else {}),
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            body = response.read().decode("utf-8")
            return json.loads(body) if body else None
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")[:1000]
        raise OperatorError(f"GitHub API {exc.code}: {detail}") from exc
    except urllib.error.URLError as exc:
        raise OperatorError(f"GitHub API unavailable: {exc.reason}") from exc


def fetch_comments(config: Config, token: str) -> list[dict[str, Any]]:
    owner, repo = config.repository.split("/", 1)
    all_comments: list[dict[str, Any]] = []
    for page in range(1, 21):
        query = urllib.parse.urlencode({"per_page": 100, "page": page})
        url = f"https://api.github.com/repos/{owner}/{repo}/issues/{config.issue_number}/comments?{query}"
        batch = github_request(token, "GET", url)
        if not isinstance(batch, list):
            raise OperatorError("unexpected GitHub comments response")
        all_comments.extend(v for v in batch if isinstance(v, dict))
        if len(batch) < 100:
            break
    return all_comments


def post_comment(config: Config, token: str, body: str) -> None:
    owner, repo = config.repository.split("/", 1)
    url = f"https://api.github.com/repos/{owner}/{repo}/issues/{config.issue_number}/comments"
    github_request(token, "POST", url, {"body": body})


def extract_marked_json(body: str, marker: str) -> dict[str, Any] | None:
    marker_pos = body.find(marker)
    if marker_pos < 0:
        return None
    tail = body[marker_pos + len(marker) :].lstrip()
    if tail.startswith("```json"):
        tail = tail[len("```json") :].lstrip("\r\n ")
    elif tail.startswith("```"):
        tail = tail[len("```") :].lstrip("\r\n ")
    brace = tail.find("{")
    if brace < 0:
        raise OperatorError("marked task contains no JSON object")
    try:
        value, _ = json.JSONDecoder().raw_decode(tail[brace:])
    except json.JSONDecodeError as exc:
        raise OperatorError(f"invalid marked task JSON: {exc}") from exc
    if not isinstance(value, dict):
        raise OperatorError("marked task JSON must be an object")
    return value


def validate_task(task: dict[str, Any], config: Config) -> dict[str, Any]:
    if task.get("schema") != "WS_TASK_V1":
        raise OperatorError("unsupported task schema")

    task_id = str(task.get("task_id", ""))
    if not TASK_ID_RE.fullmatch(task_id):
        raise OperatorError("invalid task_id")

    action = str(task.get("action", ""))
    if action not in ALLOWED_ACTIONS:
        raise OperatorError(f"action is not allowlisted: {action}")

    target = str(task.get("target_host", "ANY"))
    if target not in {"ANY", "*", config.host_id}:
        raise OperatorError(f"task targets {target}, not {config.host_id}")

    issued_at = parse_iso(str(task.get("issued_at", "")))
    if issued_at > utc_now() + dt.timedelta(minutes=5):
        raise OperatorError("task issued_at is in the future")

    expires_raw = task.get("expires_at")
    if expires_raw and parse_iso(str(expires_raw)) < utc_now():
        raise OperatorError("task has expired")

    parameters = task.get("parameters", {})
    if not isinstance(parameters, dict):
        raise OperatorError("task parameters must be an object")

    forbidden = {"command", "shell", "script", "powershell", "bash", "cmd"}
    if forbidden.intersection(parameters):
        raise OperatorError("task parameters may not contain shell execution fields")

    return {
        "schema": "WS_TASK_V1",
        "task_id": task_id,
        "action": action,
        "target_host": target,
        "issued_at": iso_utc(issued_at),
        "expires_at": task.get("expires_at"),
        "required_main_commit": str(task.get("required_main_commit", "")).strip(),
        "parameters": parameters,
    }


def load_state(path: pathlib.Path) -> dict[str, Any]:
    if not path.exists():
        return {"processed": {}}
    try:
        state = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {"processed": {}}
    if not isinstance(state, dict) or not isinstance(state.get("processed"), dict):
        return {"processed": {}}
    return state


def save_state(path: pathlib.Path, state: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", delete=False, dir=path.parent) as handle:
        json.dump(state, handle, ensure_ascii=False, indent=2, sort_keys=True)
        handle.write("\n")
        tmp = pathlib.Path(handle.name)
    os.replace(tmp, path)


def truncate_text(value: str, limit: int = 6000) -> str:
    value = value.replace("\x00", "")
    return value if len(value) <= limit else value[:limit] + "\n...[truncated]"


def receipt_comment(receipt: dict[str, Any]) -> str:
    return f"{RECEIPT_MARKER}\n```json\n{json.dumps(receipt, ensure_ascii=False, indent=2, sort_keys=True)}\n```"


def run_handler(task: dict[str, Any], config: Config) -> tuple[str, dict[str, Any]]:
    action_script = config.repository_root / "local_operator" / "actions" / "deploy_chatgpt_desktop_bridge.py"
    if not action_script.exists():
        raise OperatorError(f"missing built-in action handler: {action_script}")

    command = [
        sys.executable,
        str(action_script),
        "--repo-root",
        str(config.repository_root),
        "--task-json",
        json.dumps(task, ensure_ascii=False),
    ]
    if task["action"] == "verify_white_space_bridge":
        command.append("--verify-only")

    started = time.monotonic()
    result = subprocess.run(
        command,
        cwd=config.repository_root,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        timeout=1800,
        env={**os.environ, "WS_OPERATOR_HOST_ID": config.host_id},
    )
    duration = round(time.monotonic() - started, 3)
    output = truncate_text(result.stdout.strip())
    error = truncate_text(result.stderr.strip())

    details: dict[str, Any] = {
        "return_code": result.returncode,
        "duration_seconds": duration,
        "stdout": output,
        "stderr": error,
    }
    status = "PASS" if result.returncode == 0 else "BLOCKED"
    return status, details


def process_once(config: Config, token: str) -> int:
    state_path = config.state_dir / "operator_state.json"
    state = load_state(state_path)
    processed: dict[str, Any] = state["processed"]
    comments = fetch_comments(config, token)
    work_count = 0

    for comment in comments:
        body = str(comment.get("body", ""))
        if TASK_MARKER not in body:
            continue
        comment_id = str(comment.get("id", ""))
        author = str((comment.get("user") or {}).get("login", ""))
        if comment_id in processed:
            continue

        try:
            if author not in config.allowed_authors:
                raise OperatorError(f"task author is not allowlisted: {author}")
            raw_task = extract_marked_json(body, TASK_MARKER)
            if raw_task is None:
                continue
            task = validate_task(raw_task, config)
            task_id = task["task_id"]
            if any(v.get("task_id") == task_id for v in processed.values() if isinstance(v, dict)):
                processed[comment_id] = {"task_id": task_id, "status": "DUPLICATE", "at": iso_utc()}
                save_state(state_path, state)
                continue

            ack = {
                "schema": "WS_RECEIPT_V1",
                "task_id": task_id,
                "host_id": config.host_id,
                "phase": "ACK",
                "status": "ACCEPTED",
                "at": iso_utc(),
                "source_comment_id": comment_id,
            }
            post_comment(config, token, receipt_comment(ack))

            status, details = run_handler(task, config)
            final_receipt = {
                "schema": "WS_RECEIPT_V1",
                "task_id": task_id,
                "host_id": config.host_id,
                "phase": "FINAL",
                "status": status,
                "at": iso_utc(),
                "action": task["action"],
                "details": details,
            }
            post_comment(config, token, receipt_comment(final_receipt))
            processed[comment_id] = {"task_id": task_id, "status": status, "at": iso_utc()}
            work_count += 1
        except Exception as exc:  # fail closed and report a bounded rejection
            rejection = {
                "schema": "WS_RECEIPT_V1",
                "task_id": "UNKNOWN",
                "host_id": config.host_id,
                "phase": "REJECT",
                "status": "BLOCKED",
                "at": iso_utc(),
                "source_comment_id": comment_id,
                "reason": truncate_text(str(exc), 1200),
            }
            try:
                post_comment(config, token, receipt_comment(rejection))
            finally:
                processed[comment_id] = {"task_id": "UNKNOWN", "status": "REJECTED", "at": iso_utc()}
        save_state(state_path, state)

    return work_count


def acquire_lock(path: pathlib.Path) -> int:
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    except FileExistsError as exc:
        raise OperatorError(f"operator lock already exists: {path}") from exc
    os.write(fd, str(os.getpid()).encode("ascii"))
    return fd


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--config",
        type=pathlib.Path,
        default=pathlib.Path(__file__).with_name("operator_config.json"),
    )
    parser.add_argument("--once", action="store_true", help="poll once and exit")
    args = parser.parse_args()

    config = load_config(args.config.resolve())
    config.state_dir.mkdir(parents=True, exist_ok=True)
    lock_path = config.state_dir / "operator.lock"
    lock_fd = acquire_lock(lock_path)

    try:
        token = gh_token()
        while True:
            try:
                count = process_once(config, token)
                print(json.dumps({"at": iso_utc(), "processed": count}, sort_keys=True), flush=True)
            except Exception as exc:
                print(json.dumps({"at": iso_utc(), "error": str(exc)}, sort_keys=True), file=sys.stderr, flush=True)
                if args.once:
                    return 2
            if args.once:
                return 0
            time.sleep(config.poll_seconds)
    finally:
        os.close(lock_fd)
        try:
            lock_path.unlink()
        except FileNotFoundError:
            pass


if __name__ == "__main__":
    raise SystemExit(main())
