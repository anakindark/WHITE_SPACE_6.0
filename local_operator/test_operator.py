from __future__ import annotations

import datetime as dt
import importlib.util
import pathlib
import sys
import tempfile
import unittest

MODULE_PATH = pathlib.Path(__file__).with_name("ws_local_operator.py")
SPEC = importlib.util.spec_from_file_location("ws_local_operator", MODULE_PATH)
assert SPEC and SPEC.loader
operator = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = operator
SPEC.loader.exec_module(operator)


class LocalOperatorTests(unittest.TestCase):
    def config(self, host_id: str = "PC_BIRD"):
        return operator.Config(
            repository="anakindark/WHITE_SPACE_6.0",
            issue_number=4,
            allowed_authors=frozenset({"anakindark"}),
            host_id=host_id,
            poll_seconds=30,
            state_dir=pathlib.Path(tempfile.gettempdir()) / "ws-operator-test-state",
            repository_root=pathlib.Path(tempfile.gettempdir()) / "ws-operator-test-repo",
        )

    def task(self):
        now = dt.datetime.now(dt.timezone.utc)
        return {
            "schema": "WS_TASK_V1",
            "task_id": "ws-test-001",
            "action": "verify_white_space_bridge",
            "target_host": "ANY",
            "issued_at": now.isoformat(),
            "expires_at": (now + dt.timedelta(hours=1)).isoformat(),
            "required_main_commit": "abc123",
            "parameters": {"restart_test": False},
        }

    def test_extract_marked_json(self):
        body = f"prefix\n{operator.TASK_MARKER}\n```json\n{{\"schema\":\"WS_TASK_V1\"}}\n```"
        parsed = operator.extract_marked_json(body, operator.TASK_MARKER)
        self.assertEqual(parsed["schema"], "WS_TASK_V1")

    def test_valid_task(self):
        task = operator.validate_task(self.task(), self.config())
        self.assertEqual(task["action"], "verify_white_space_bridge")
        self.assertEqual(task["target_host"], "ANY")

    def test_rejects_unknown_action(self):
        task = self.task()
        task["action"] = "run_arbitrary_shell"
        with self.assertRaises(operator.OperatorError):
            operator.validate_task(task, self.config())

    def test_rejects_shell_fields(self):
        task = self.task()
        task["parameters"] = {"shell": "rm -rf /"}
        with self.assertRaises(operator.OperatorError):
            operator.validate_task(task, self.config())

    def test_rejects_other_host(self):
        task = self.task()
        task["target_host"] = "OTHER_HOST"
        with self.assertRaises(operator.OperatorError):
            operator.validate_task(task, self.config())

    def test_expired_task(self):
        task = self.task()
        task["expires_at"] = (dt.datetime.now(dt.timezone.utc) - dt.timedelta(seconds=1)).isoformat()
        with self.assertRaises(operator.OperatorError):
            operator.validate_task(task, self.config())


if __name__ == "__main__":
    unittest.main()
