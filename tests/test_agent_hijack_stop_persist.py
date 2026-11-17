"""Persist-hijack ingress tests for Agent Hijack stop."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from sase.agent.hijack.stop import HijackStopResult
from tests._agent_hijack_stop_support import AGENT


def test_persist_hijack_uses_the_request_sidecar(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from sase.main.parser import create_parser
    from sase.ops import (
        DurableOperationRequest,
        read_operation_result,
        write_operation_request,
    )
    from sase.ops.commands.agent import handle_agent_operation

    request_path = tmp_path / "req.json"
    result_path = tmp_path / "res.json"
    write_operation_request(
        request_path,
        DurableOperationRequest(
            operation="agent.persist-hijack",
            payload={"name": AGENT, "reason": "stalled"},
        ),
    )
    captured: dict[str, Any] = {}

    def fake_stop(name: str, **kwargs: Any) -> HijackStopResult:
        captured["name"] = name
        captured["reason"] = kwargs.get("reason")
        return HijackStopResult(
            status="held",
            message="hijacked",
            exit_code=0,
            hijack_id="h-9",
            record={"workspace_num": 4, "artifacts_dir": "/tmp/a"},
        )

    monkeypatch.setattr(
        "sase.ops.commands._agent_persist_hijack.stop_agent_for_hijack",
        fake_stop,
    )
    args = create_parser().parse_args(
        ["agent", "persist-hijack", "-Q", str(request_path), "-R", str(result_path)]
    )
    monkeypatch.setenv("SASE_PROC_ID", "proc-hijack")
    assert handle_agent_operation(args) == 0
    assert captured == {"name": AGENT, "reason": "stalled"}
    loaded = read_operation_result(
        result_path,
        expected_operation="agent.persist-hijack",
        expected_proc_id="proc-hijack",
    )
    assert loaded.success is True
    assert loaded.payload["status"] == "held"
    assert loaded.payload["record"]["workspace_num"] == 4


def test_persist_hijack_cancel_uses_latch_backend(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from sase.main.parser import create_parser
    from sase.ops import (
        DurableOperationRequest,
        read_operation_result,
        write_operation_request,
    )
    from sase.ops.commands.agent import handle_agent_operation

    request_path = tmp_path / "req.json"
    result_path = tmp_path / "res.json"
    write_operation_request(
        request_path,
        DurableOperationRequest(
            operation="agent.persist-hijack",
            payload={
                "name": AGENT,
                "action": "cancel",
                "hijack_id": "h-latched",
                "target_key": "proj:session-1",
            },
        ),
    )
    captured: dict[str, Any] = {}

    def fake_cancel(target_key: str, *, hijack_id: str | None = None) -> dict[str, Any]:
        captured["target_key"] = target_key
        captured["hijack_id"] = hijack_id
        return {
            "verdict": "cancelled",
            "hijack_id": hijack_id,
            "target_key": target_key,
            "message": "latch cancelled",
            "record": {"state": "cancelled", "hijack_id": hijack_id},
        }

    monkeypatch.setattr(
        "sase.agent.hijack.latch.cancel_latch",
        fake_cancel,
    )
    args = create_parser().parse_args(
        ["agent", "persist-hijack", "-Q", str(request_path), "-R", str(result_path)]
    )
    monkeypatch.setenv("SASE_PROC_ID", "proc-cancel")
    assert handle_agent_operation(args) == 0
    assert captured == {"target_key": "proj:session-1", "hijack_id": "h-latched"}
    loaded = read_operation_result(
        result_path,
        expected_operation="agent.persist-hijack",
        expected_proc_id="proc-cancel",
    )
    assert loaded.success is True
    assert loaded.payload["status"] == "cancelled"
    assert loaded.payload["action"] == "cancel"


def test_persist_hijack_force_uses_latch_backend(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from sase.main.parser import create_parser
    from sase.ops import (
        DurableOperationRequest,
        read_operation_result,
        write_operation_request,
    )
    from sase.ops.commands.agent import handle_agent_operation

    request_path = tmp_path / "req.json"
    result_path = tmp_path / "res.json"
    write_operation_request(
        request_path,
        DurableOperationRequest(
            operation="agent.persist-hijack",
            payload={
                "name": AGENT,
                "action": "now",
                "hijack_id": "h-latched",
                "project_file": "/tmp/sample.sase",
                "session_name": "session-1",
            },
        ),
    )
    captured: dict[str, Any] = {}

    def fake_force(target_key: str, *, hijack_id: str | None = None) -> dict[str, Any]:
        captured["target_key"] = target_key
        captured["hijack_id"] = hijack_id
        return {
            "verdict": "applied",
            "hijack_id": hijack_id,
            "target_key": target_key,
            "forced": True,
            "message": "forced",
            "record": {"state": "held", "hijack_id": hijack_id, "forced": True},
        }

    monkeypatch.setattr(
        "sase.agent.hijack.ledger.target_key_for",
        lambda project_file, session: f"{project_file}:{session}",
    )
    monkeypatch.setattr(
        "sase.agent.hijack.latch.force_hijack_latch",
        fake_force,
    )
    args = create_parser().parse_args(
        ["agent", "persist-hijack", "-Q", str(request_path), "-R", str(result_path)]
    )
    monkeypatch.setenv("SASE_PROC_ID", "proc-force")
    assert handle_agent_operation(args) == 0
    assert captured["hijack_id"] == "h-latched"
    assert captured["target_key"].endswith(":session-1")
    loaded = read_operation_result(
        result_path,
        expected_operation="agent.persist-hijack",
        expected_proc_id="proc-force",
    )
    assert loaded.success is True
    assert loaded.payload["status"] == "held"
    assert loaded.payload["action"] == "force"
    assert loaded.payload["forced"] is True


def test_persist_hijack_latched_stop_is_success(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from sase.main.parser import create_parser
    from sase.ops import (
        DurableOperationRequest,
        read_operation_result,
        write_operation_request,
    )
    from sase.ops.commands.agent import handle_agent_operation

    request_path = tmp_path / "req.json"
    result_path = tmp_path / "res.json"
    write_operation_request(
        request_path,
        DurableOperationRequest(
            operation="agent.persist-hijack",
            payload={"name": AGENT, "action": "hijack"},
        ),
    )

    def fake_stop(name: str, **kwargs: Any) -> HijackStopResult:
        del name, kwargs
        return HijackStopResult(
            status="latched",
            message="Hijack latched; waiting for a safe boundary",
            exit_code=3,
            hijack_id="h-latched",
            record={"state": "latched", "workspace_num": 4},
        )

    monkeypatch.setattr(
        "sase.ops.commands._agent_persist_hijack.stop_agent_for_hijack",
        fake_stop,
    )
    args = create_parser().parse_args(
        ["agent", "persist-hijack", "-Q", str(request_path), "-R", str(result_path)]
    )
    monkeypatch.setenv("SASE_PROC_ID", "proc-latched")
    assert handle_agent_operation(args) == 0
    loaded = read_operation_result(
        result_path,
        expected_operation="agent.persist-hijack",
        expected_proc_id="proc-latched",
    )
    assert loaded.success is True
    assert loaded.payload["status"] == "latched"
