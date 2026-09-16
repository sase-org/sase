"""Gate-shell transaction intent-marker lifecycle."""

from __future__ import annotations

from contextlib import nullcontext
from dataclasses import replace
from pathlib import Path
from typing import Any

import pytest

from sase.agent.gate_intent import list_gate_intents
from sase.finalizers.owned_turn import SASE_FINALIZER_OWNED_TURN_ENV
from sase.gate_shell import transaction as transaction_module
from sase.gate_shell.models import GateShellLaneError, GateShellRecord
from sase.gate_shell.start_claim import GateClaimMove
from sase.gate_shell.transaction import create_gate_shell
from sase.notification_gates.model_results import GateCreationResult
from sase.notification_gates.model_validation import GateError
from sase.running_field import ClaimResult


def _shell_gate_spec(request_id: str = "intent-one") -> dict[str, Any]:
    return {
        "schema_version": 3,
        "request_id": request_id,
        "kind": "custom",
        "producer": {"agent": "agent-1"},
        "payload": {},
        "presentation": {"title": "Review action"},
        "query": "approve OR reject",
        "primary_branch": ["approve"],
        "options": [
            {
                "id": "approve",
                "label": "Approve",
                "command": {"argv": ["commands/approve"]},
            },
            {
                "id": "reject",
                "label": "Reject",
                "command": {"argv": ["commands/reject"]},
            },
        ],
        "shell": {
            "suffix": "--gate-test",
            "next": {"prompt": "Continue after approval."},
        },
    }


def _record(tmp_path: Path, state: str = "pending") -> GateShellRecord:
    return GateShellRecord(
        gate_id="intent-one",
        member_agent_name="agent--gate-test",
        lane="agent",
        project_name="proj",
        artifacts_dir=str(tmp_path / "member"),
        timestamp="20260916120000",
        kind="custom",
        gate_state=state,  # type: ignore[arg-type]
        start_status="GATE",
        stop_status="GATED",
        accent="yellow",
        label="custom",
        reason="test",
        creator_agent="agent",
        bundle_path=None,
        notification_id=None,
        timeout_seconds=30.0,
        request_fingerprint=None,
        workspace_policy="inherit",
    )


def _creation_result(tmp_path: Path, *, auto: bool = False) -> GateCreationResult:
    return GateCreationResult(
        schema_version=1,
        notification_id=None,
        request_id="intent-one",
        kind="custom",
        bundle_path=tmp_path / "bundle",
        request_path=tmp_path / "bundle" / "request.json",
        response_path=tmp_path / "bundle" / "response.json",
        preview_path=None,
        continuation_mode="none",
        auto_resolution={"state": "resolved"} if auto else {},
        hashes={},
    )


def _install_transaction_fakes(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    *,
    gate_result: GateCreationResult | None = None,
) -> GateShellRecord:
    record = _record(tmp_path)
    creator = transaction_module._CreatorContext(
        project_name="proj",
        project_file=str(tmp_path / "proj.sase"),
        artifacts_dir=str(tmp_path / "creator"),
        timestamp="20260916115959",
        target_name="agent",
        durable_lane="agent",
        meta={"name": "agent"},
        workspace_num=None,
        runner_pid=None,
        cl_name=None,
    )
    monkeypatch.setattr(transaction_module, "_resolve_project_name", lambda: "proj")
    monkeypatch.setattr(
        transaction_module, "_resolve_creator", lambda _project: creator
    )
    monkeypatch.setattr(
        transaction_module, "_gate_lane_lock_path", lambda *_: tmp_path / "lock"
    )
    monkeypatch.setattr(
        transaction_module, "log_file_lock", lambda _path: nullcontext()
    )
    monkeypatch.setattr(
        transaction_module, "find_gate_shell_by_gate_id", lambda *_: None
    )
    monkeypatch.setattr(transaction_module, "has_any_gate_shell", lambda *_: False)
    monkeypatch.setattr(
        transaction_module,
        "create_gate_shell_member",
        lambda *args, **kwargs: record.artifacts_dir,
    )
    monkeypatch.setattr(
        transaction_module,
        "move_gate_shell_claim",
        lambda *args, **kwargs: GateClaimMove(ClaimResult(True), None, None, "inherit"),
    )
    monkeypatch.setattr(transaction_module, "_record_creator_claim", lambda *_: None)
    monkeypatch.setattr(transaction_module, "_read_required_record", lambda *_: record)
    monkeypatch.setattr(
        transaction_module,
        "_record_with_gate_result",
        lambda _project, gate_record, _result: gate_record,
    )
    monkeypatch.setattr(
        transaction_module,
        "settle_gate_shell",
        lambda gate_record, **kwargs: replace(gate_record, gate_state="answered"),
    )
    monkeypatch.setattr(
        transaction_module, "restore_gate_shell_claim", lambda *_, **__: None
    )
    monkeypatch.setattr(
        transaction_module,
        "create_gate",
        lambda _spec: gate_result or _creation_result(tmp_path),
    )
    return record


def _set_agent_env(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> Path:
    artifacts_dir = tmp_path / "artifacts"
    artifacts_dir.mkdir()
    monkeypatch.setenv("SASE_AGENT", "1")
    monkeypatch.setenv("SASE_ARTIFACTS_DIR", str(artifacts_dir))
    monkeypatch.delenv(SASE_FINALIZER_OWNED_TURN_ENV, raising=False)
    return artifacts_dir


def test_keyboard_interrupt_leaves_intent_marker(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    artifacts_dir = _set_agent_env(tmp_path, monkeypatch)
    monkeypatch.setattr(transaction_module, "_resolve_project_name", lambda: "proj")
    monkeypatch.setattr(
        transaction_module,
        "_resolve_creator",
        lambda _project: (_ for _ in ()).throw(KeyboardInterrupt()),
    )
    monkeypatch.setattr(
        transaction_module,
        "create_gate_shell_member",
        lambda *args, **kwargs: pytest.fail("member creation must not run"),
    )

    with pytest.raises(KeyboardInterrupt):
        create_gate_shell(_shell_gate_spec())

    intents = list_gate_intents(artifacts_dir)
    assert len(intents) == 1
    assert intents[0].kind == "custom"
    assert intents[0].request_id == "intent-one"


def test_clean_lane_error_clears_intent_marker(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    artifacts_dir = _set_agent_env(tmp_path, monkeypatch)
    monkeypatch.setattr(transaction_module, "_resolve_project_name", lambda: "proj")
    monkeypatch.setattr(
        transaction_module,
        "_resolve_creator",
        lambda _project: (_ for _ in ()).throw(GateShellLaneError("clean failure")),
    )

    with pytest.raises(GateShellLaneError, match="clean failure"):
        create_gate_shell(_shell_gate_spec())

    assert list_gate_intents(artifacts_dir) == []


def test_clean_gate_error_clears_intent_marker(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    artifacts_dir = _set_agent_env(tmp_path, monkeypatch)
    _install_transaction_fakes(tmp_path, monkeypatch)
    monkeypatch.setattr(
        transaction_module,
        "create_gate",
        lambda _spec: (_ for _ in ()).throw(
            GateError("invalid", "gate", "clean failure")
        ),
    )

    with pytest.raises(GateError, match="clean failure"):
        create_gate_shell(_shell_gate_spec())

    assert list_gate_intents(artifacts_dir) == []


def test_auto_resolved_gate_clears_intent_marker(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    artifacts_dir = _set_agent_env(tmp_path, monkeypatch)
    _install_transaction_fakes(
        tmp_path,
        monkeypatch,
        gate_result=_creation_result(tmp_path, auto=True),
    )

    creation = create_gate_shell(_shell_gate_spec())

    assert creation.record.is_terminal
    assert list_gate_intents(artifacts_dir) == []


def test_non_terminal_creation_keeps_intent_for_handoff(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    artifacts_dir = _set_agent_env(tmp_path, monkeypatch)
    _install_transaction_fakes(tmp_path, monkeypatch)

    creation = create_gate_shell(_shell_gate_spec())

    assert creation.should_handoff
    intents = list_gate_intents(artifacts_dir)
    assert len(intents) == 1
    assert intents[0].request_id == "intent-one"


def test_finalizer_owned_turn_writes_no_intent(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    artifacts_dir = _set_agent_env(tmp_path, monkeypatch)
    monkeypatch.setenv(SASE_FINALIZER_OWNED_TURN_ENV, "1")

    with pytest.raises(transaction_module.GateShellError, match="host finalizer turn"):
        create_gate_shell(_shell_gate_spec())

    assert list_gate_intents(artifacts_dir) == []
