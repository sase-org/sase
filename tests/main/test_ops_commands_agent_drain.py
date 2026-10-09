"""Agent drain operation tests.

Split from ``test_ops_commands``; the original module re-exports these
tests so its import path keeps working.
"""

from __future__ import annotations

import argparse
from pathlib import Path
from types import SimpleNamespace
from typing import Any

from sase.main.parser import create_parser
from sase.ops import (
    DurableOperationRequest,
    read_operation_result,
    write_operation_request,
)
from sase.ops.commands.agent import handle_agent_operation


def test_agent_drain_operation_writes_result_and_preserves_exit_code(
    monkeypatch: Any, tmp_path: Path
) -> None:
    result_path = tmp_path / "drain-res.json"
    expected_payload = {
        "provider": "claude",
        "counts": {"relaunched": 0, "failed": 0, "skipped": 0},
    }

    def fake_run(
        _args: argparse.Namespace, *, report_fn: Any = None
    ) -> SimpleNamespace:
        result = SimpleNamespace(
            exit_code=2,
            success=False,
            message="No agents can be relaunched for this disabled provider.",
            payload=expected_payload,
        )
        if report_fn is not None:
            report_fn(result)
        return result

    monkeypatch.setattr("sase.agents.cli_drain.run_agents_drain", fake_run)
    args = create_parser().parse_args(
        ["agent", "drain", "claude", "-j", "-R", str(result_path)]
    )
    monkeypatch.setenv("SASE_PROC_ID", "proc-drain")

    assert handle_agent_operation(args) == 2
    loaded = read_operation_result(
        result_path, expected_operation="agent.drain", expected_proc_id="proc-drain"
    )
    assert loaded.success is False
    assert loaded.payload == expected_payload


def test_agent_drain_operation_owns_notification_when_payload_says_notify(
    monkeypatch: Any, tmp_path: Path
) -> None:
    """An automatic usage-limit drain settles its trigger and notifies once.

    ``handle_possible_usage_limit`` submits the drain with a request payload
    carrying ``notify: True`` plus the trigger context. The operation
    dispatcher must settle that trigger agent before planning and hand the
    final result to the notifier -- an ordinary manual drain (no request
    sidecar, or one without ``notify``) must do neither.
    """
    request_path = tmp_path / "drain-req.json"
    result_path = tmp_path / "drain-res.json"
    write_operation_request(
        request_path,
        DurableOperationRequest(
            operation="agent.drain",
            payload={
                "notify": True,
                "provider": "claude",
                "matched_pattern": "usage limit reached",
                "raw_message": "usage limit reached",
                "disable_seconds": 3600.0,
                "expires_at": None,
                "used_reset_hint": False,
                "trigger_agent": "sase-mf",
                "trigger_artifacts_dir": "/tmp/sase-mf-artifacts",
                "trigger_model": "opus@high",
            },
        ),
    )
    payload = {"provider": "claude", "counts": {"relaunched": 1}}

    def fake_run(
        _args: argparse.Namespace, *, report_fn: Any = None
    ) -> SimpleNamespace:
        result = SimpleNamespace(
            exit_code=0, success=True, message="Drained", payload=payload
        )
        if report_fn is not None:
            report_fn(result)
        return result

    settled: list[Any] = []
    notified: list[tuple[Any, Any]] = []
    monkeypatch.setattr("sase.agents.cli_drain.run_agents_drain", fake_run)
    monkeypatch.setattr(
        "sase.ops.commands._agent_drain_notify.settle_drain_trigger_agent",
        lambda name, **kwargs: settled.append(
            (name, kwargs.get("trigger_artifacts_dir"))
        ),
    )
    monkeypatch.setattr(
        "sase.ops.commands._agent_drain_notify.send_usage_limit_drain_notification",
        lambda trigger, result: notified.append((trigger, result)),
    )
    args = create_parser().parse_args(
        [
            "agent",
            "drain",
            "claude",
            "-j",
            "-Q",
            str(request_path),
            "-R",
            str(result_path),
        ]
    )
    monkeypatch.setenv("SASE_PROC_ID", "proc-auto-drain")

    assert handle_agent_operation(args) == 0
    assert settled == [("sase-mf", "/tmp/sase-mf-artifacts")]
    assert len(notified) == 1
    trigger, result = notified[0]
    assert trigger["trigger_agent"] == "sase-mf"
    assert result.payload == payload


def test_agent_drain_operation_without_notify_payload_skips_notification(
    monkeypatch: Any, tmp_path: Path
) -> None:
    result_path = tmp_path / "drain-res.json"

    def fake_run(
        _args: argparse.Namespace, *, report_fn: Any = None
    ) -> SimpleNamespace:
        result = SimpleNamespace(
            exit_code=0, success=True, message="Drained", payload={}
        )
        if report_fn is not None:
            report_fn(result)
        return result

    settled: list[Any] = []
    notified: list[Any] = []
    monkeypatch.setattr("sase.agents.cli_drain.run_agents_drain", fake_run)
    monkeypatch.setattr(
        "sase.ops.commands._agent_drain_notify.settle_drain_trigger_agent",
        lambda name, **_k: settled.append(name),
    )
    monkeypatch.setattr(
        "sase.ops.commands._agent_drain_notify.send_usage_limit_drain_notification",
        lambda trigger, result: notified.append((trigger, result)),
    )
    args = create_parser().parse_args(
        ["agent", "drain", "claude", "-j", "-R", str(result_path)]
    )
    monkeypatch.setenv("SASE_PROC_ID", "proc-manual-drain")

    assert handle_agent_operation(args) == 0
    assert settled == []
    assert notified == []


def test_agent_drain_automatic_nothing_to_drain_is_successful_noop(
    monkeypatch: Any, tmp_path: Path
) -> None:
    request_path = tmp_path / "drain-req.json"
    result_path = tmp_path / "drain-res.json"
    write_operation_request(
        request_path,
        DurableOperationRequest(
            operation="agent.drain",
            payload={"automatic": True, "provider": "claude"},
        ),
    )
    expected_payload = {
        "provider": "claude",
        "counts": {"relaunched": 0, "failed": 0, "skipped": 0},
        "error": {
            "reason": "nothing_to_drain",
            "message": "No agents can be relaunched for this disabled provider.",
        },
    }

    def fake_run(
        _args: argparse.Namespace, *, report_fn: Any = None
    ) -> SimpleNamespace:
        result = SimpleNamespace(
            exit_code=2,
            success=False,
            message="No agents can be relaunched for this disabled provider.",
            payload=expected_payload,
        )
        if report_fn is not None:
            report_fn(result)
        return result

    monkeypatch.setattr("sase.agents.cli_drain.run_agents_drain", fake_run)
    args = create_parser().parse_args(
        [
            "agent",
            "drain",
            "claude",
            "-j",
            "-Q",
            str(request_path),
            "-R",
            str(result_path),
        ]
    )
    monkeypatch.setenv("SASE_PROC_ID", "proc-auto-noop")

    assert handle_agent_operation(args) == 0
    loaded = read_operation_result(
        result_path, expected_operation="agent.drain", expected_proc_id="proc-auto-noop"
    )
    assert loaded.success is True
    assert loaded.payload == expected_payload


def test_agent_drain_automatic_not_disabled_is_successful_noop(
    monkeypatch: Any, tmp_path: Path
) -> None:
    request_path = tmp_path / "drain-req.json"
    result_path = tmp_path / "drain-res.json"
    write_operation_request(
        request_path,
        DurableOperationRequest(
            operation="agent.drain",
            payload={"automatic": True, "provider": "claude"},
        ),
    )
    expected_payload = {
        "provider": "claude",
        "error": {"reason": "not_disabled", "message": "gone"},
    }

    def fake_run(
        _args: argparse.Namespace, *, report_fn: Any = None
    ) -> SimpleNamespace:
        result = SimpleNamespace(
            exit_code=2, success=False, message="gone", payload=expected_payload
        )
        if report_fn is not None:
            report_fn(result)
        return result

    monkeypatch.setattr("sase.agents.cli_drain.run_agents_drain", fake_run)
    args = create_parser().parse_args(
        [
            "agent",
            "drain",
            "claude",
            "-j",
            "-Q",
            str(request_path),
            "-R",
            str(result_path),
        ]
    )
    monkeypatch.setenv("SASE_PROC_ID", "proc-auto-not-disabled")

    assert handle_agent_operation(args) == 0
    loaded = read_operation_result(
        result_path,
        expected_operation="agent.drain",
        expected_proc_id="proc-auto-not-disabled",
    )
    assert loaded.success is True
    assert loaded.payload == expected_payload


def test_agent_drain_non_automatic_nothing_to_drain_stays_failed(
    monkeypatch: Any, tmp_path: Path
) -> None:
    result_path = tmp_path / "drain-res.json"
    expected_payload = {
        "provider": "claude",
        "error": {"reason": "nothing_to_drain", "message": "empty"},
    }

    def fake_run(
        _args: argparse.Namespace, *, report_fn: Any = None
    ) -> SimpleNamespace:
        result = SimpleNamespace(
            exit_code=2, success=False, message="empty", payload=expected_payload
        )
        if report_fn is not None:
            report_fn(result)
        return result

    monkeypatch.setattr("sase.agents.cli_drain.run_agents_drain", fake_run)
    args = create_parser().parse_args(
        ["agent", "drain", "claude", "-j", "-R", str(result_path)]
    )
    monkeypatch.setenv("SASE_PROC_ID", "proc-manual-empty")

    assert handle_agent_operation(args) == 2
    loaded = read_operation_result(
        result_path,
        expected_operation="agent.drain",
        expected_proc_id="proc-manual-empty",
    )
    assert loaded.success is False


def test_agent_drain_automatic_move_failed_still_fails(
    monkeypatch: Any, tmp_path: Path
) -> None:
    request_path = tmp_path / "drain-req.json"
    result_path = tmp_path / "drain-res.json"
    write_operation_request(
        request_path,
        DurableOperationRequest(
            operation="agent.drain",
            payload={"automatic": True, "provider": "claude"},
        ),
    )
    expected_payload = {
        "provider": "claude",
        "error": {"reason": "move_failed", "message": "1 drain move(s) failed."},
    }

    def fake_run(
        _args: argparse.Namespace, *, report_fn: Any = None
    ) -> SimpleNamespace:
        result = SimpleNamespace(
            exit_code=1,
            success=False,
            message="1 drain move(s) failed.",
            payload=expected_payload,
        )
        if report_fn is not None:
            report_fn(result)
        return result

    monkeypatch.setattr("sase.agents.cli_drain.run_agents_drain", fake_run)
    args = create_parser().parse_args(
        [
            "agent",
            "drain",
            "claude",
            "-j",
            "-Q",
            str(request_path),
            "-R",
            str(result_path),
        ]
    )
    monkeypatch.setenv("SASE_PROC_ID", "proc-auto-failed")

    assert handle_agent_operation(args) == 1
    loaded = read_operation_result(
        result_path,
        expected_operation="agent.drain",
        expected_proc_id="proc-auto-failed",
    )
    assert loaded.success is False
