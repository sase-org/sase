"""Durable persist-recover tests for hijack release recovery."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from sase.agent.hijack.recover_common import RecoveryResult


class TestPersistRecoverRelease:
    def _request(self, tmp_path: Path, payload: dict[str, Any]) -> tuple[Any, Path]:
        from sase.main.parser import create_parser
        from sase.ops import DurableOperationRequest, write_operation_request
        from sase.ops.names import AGENT_PERSIST_RECOVER

        request_path = tmp_path / "req.json"
        result_path = tmp_path / "res.json"
        write_operation_request(
            request_path,
            DurableOperationRequest(operation=AGENT_PERSIST_RECOVER, payload=payload),
        )
        args = create_parser().parse_args(
            [
                "agent",
                "persist-recover",
                "-Q",
                str(request_path),
                "-R",
                str(result_path),
            ]
        )
        return args, result_path

    def test_persist_recover_dismiss(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from sase.ops import read_operation_result
        from sase.ops.commands.agent import handle_agent_operation

        captured: dict[str, Any] = {}

        def release(name: str, **kwargs: Any) -> RecoveryResult:
            captured["name"] = name
            captured.update(kwargs)
            return RecoveryResult(
                kind="launched",
                hijack_id="h-123",
                revision=8,
                action="dismiss",
                message="Dismissed",
            )

        monkeypatch.setattr(
            "sase.ops.commands._agent_persist_recover.recover_release_action", release
        )
        args, result_path = self._request(
            tmp_path,
            {
                "name": "sase-7f.2",
                "action": "dismiss",
                "expected_hijack_id": "h-123",
                "expected_revision": 7,
                "discard_without_snapshot": True,
            },
        )
        monkeypatch.setenv("SASE_PROC_ID", "proc-release")
        assert handle_agent_operation(args) == 0
        assert captured["action"] == "dismiss"
        assert captured["discard_without_snapshot"] is True
        loaded = read_operation_result(result_path, expected_proc_id="proc-release")
        assert loaded.success is True
        assert loaded.payload["status"] == "launched"

    def test_persist_recover_rejects_bad_action(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from sase.ops import read_operation_result
        from sase.ops.commands.agent import handle_agent_operation

        args, result_path = self._request(
            tmp_path,
            {
                "name": "sase-7f.2",
                "action": "nuke",
                "expected_hijack_id": "h-123",
                "expected_revision": 7,
            },
        )
        monkeypatch.setenv("SASE_PROC_ID", "proc-release")
        assert handle_agent_operation(args) != 0
        loaded = read_operation_result(result_path, expected_proc_id="proc-release")
        assert loaded.success is False
        assert "must be" in (loaded.error or "")
