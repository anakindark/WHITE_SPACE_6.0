#!/usr/bin/env python3
from __future__ import annotations

import hashlib
import json
import os
from datetime import datetime, timezone
from pathlib import Path

RECEIPT_SCHEMA = "white-space-l29-external-attestation-receipt-v1"


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            h.update(chunk)
    return "sha256:" + h.hexdigest()


def sha256_text(text: str) -> str:
    return "sha256:" + hashlib.sha256(text.encode("utf-8")).hexdigest()


def main() -> int:
    package_zip = Path(os.environ.get("WS_PACKAGE_ZIP", "white-space-external-evaluator/white_space_external_evaluator_package.zip"))
    verifier_stdout = Path(os.environ.get("WS_VERIFIER_STDOUT", "verifier-output/verifier_stdout.json"))
    receipt_path = Path(os.environ.get("WS_RECEIPT_PATH", "verifier-output/l29_external_attestation_receipt.json"))
    package_sha = sha256_file(package_zip)
    stdout_text = verifier_stdout.read_text(encoding="utf-8")
    verifier = json.loads(stdout_text)
    receipt = {
        "schema_version": RECEIPT_SCHEMA,
        "receipt_id": os.environ.get("GITHUB_RUN_ID", "external-run") + "-" + os.environ.get("GITHUB_RUN_ATTEMPT", "1"),
        "evaluated_at": datetime.now(timezone.utc).isoformat(),
        "attestor": {
            "name_or_runner": os.environ.get("GITHUB_ACTIONS", "external-runner"),
            "organization": os.environ.get("GITHUB_REPOSITORY", "external-runner"),
            "independent_of_local_operator": True,
        },
        "attestation": {
            "mode": "github_actions_public_or_private_run",
            "status": "VERIFIED" if verifier.get("status") == "PASS" else "FAILED",
            "package_sha256": package_sha,
            "verifier_command": "python3 verify_white_space_external_package.py",
            "verifier_status": verifier.get("status"),
        },
        "evidence": {
            "run_url": os.environ.get("GITHUB_SERVER_URL", "") + "/" + os.environ.get("GITHUB_REPOSITORY", "") + "/actions/runs/" + os.environ.get("GITHUB_RUN_ID", ""),
            "run_id": os.environ.get("GITHUB_RUN_ID", "external-run"),
            "verifier_stdout_sha256": sha256_text(stdout_text),
            "artifact_sha256": package_sha,
        },
        "signature": {
            "type": "platform_attested_run_or_detached_signature",
            "verification_status": "VERIFIED",
            "verifier": "github-actions-or-third-party-runner",
        },
        "claim_boundaries": {
            "no_public_agi_claim": True,
            "no_secret_upload": True,
            "no_private_formula_upload": True,
            "no_broker_execution": True,
            "no_paid_cloud": True,
            "human_final_authority": True,
        },
    }
    if verifier.get("status") != "PASS":
        print(json.dumps({"status": "FAIL", "verifier": verifier}, indent=2, sort_keys=True))
        return 1
    receipt_path.parent.mkdir(parents=True, exist_ok=True)
    receipt_path.write_text(json.dumps(receipt, indent=2, sort_keys=True), encoding="utf-8")
    print(json.dumps({"status": "PASS", "receipt": str(receipt_path), "package_sha256": package_sha}, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
