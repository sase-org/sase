"""Workflow HITL producer coverage for the option-query contract."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from sase.notification_gates.executor import execute_gate_selection
from sase.notification_gates.failure_notifications import GATE_EXECUTION_FAILED_ACTION
from sase.notification_gates.models import GateError
from sase.notification_gates.service import create_gate
from sase.gate_shell.followup_policy import (
    resolve_gate_branch_presentation,
    resolve_gate_followup,
)
from sase.notifications import pending_actions
from sase.notifications.store import load_notifications
from sase.notification_gates.models import GateSpec
from sase.xprompt.workflow_hitl_gate import (
    _translate_workflow_hitl_response,
    _workflow_hitl_gate_spec,
    _workflow_hitl_shell_spec,
    create_workflow_hitl_gate,
    wait_for_workflow_hitl_gate,
)


@pytest.fixture()
def hitl_gate_home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    from sase.notification_gates import paths
    from sase.notifications import store

    monkeypatch.setattr(paths, "INTERACTION_REQUESTS_DIR", tmp_path / "requests")
    monkeypatch.setattr(store, "NOTIFICATIONS_DIR", str(tmp_path / "notifications"))
    monkeypatch.setattr(
        store,
        "NOTIFICATIONS_FILE",
        str(tmp_path / "notifications" / "notifications.jsonl"),
    )
    monkeypatch.setattr(
        pending_actions, "PENDING_ACTIONS_PATH", tmp_path / "pending.json"
    )
    monkeypatch.setattr(
        pending_actions,
        "LEGACY_TELEGRAM_PENDING_ACTIONS_PATH",
        tmp_path / "legacy.json",
    )
    store._LOAD_CACHE.clear()
    return tmp_path


def test_agent_hitl_gate_uses_singleton_option_branches(
    hitl_gate_home: Path,
) -> None:
    gate = create_workflow_hitl_gate(
        step_name="review",
        step_type="agent",
        output={"answer": 42},
        workflow_name="demo",
        artifacts_dir=str(hitl_gate_home / "artifacts"),
        has_output=True,
        output_types=None,
        timeout_seconds=60,
    )

    envelope = json.loads(gate.request_path.read_text(encoding="utf-8"))
    assert envelope["schema_version"] == 3
    assert envelope["primary_branch"] == ["accept"]
    assert envelope["query"] == "accept OR edit OR feedback OR reject"
    assert envelope["branches"] == [
        ["accept"],
        ["edit"],
        ["feedback"],
        ["reject"],
    ]

    execution = execute_gate_selection(
        gate.bundle_path,
        ["feedback"],
        {},
        feedback="Try a smaller change",
        source="test",
    )
    result = _translate_workflow_hitl_response(execution.response)
    assert result.action == "feedback"
    assert result.feedback == "Try a smaller change"


def test_command_hitl_gate_keeps_rerun_and_edit_actions(
    hitl_gate_home: Path,
) -> None:
    gate = create_workflow_hitl_gate(
        step_name="build",
        step_type="bash",
        output={"artifact": "result.json"},
        workflow_name="demo",
        artifacts_dir=str(hitl_gate_home / "artifacts"),
        has_output=True,
        output_types={"artifact": "path"},
        timeout_seconds=60,
    )
    envelope = json.loads(gate.request_path.read_text(encoding="utf-8"))
    assert envelope["query"] == "accept OR edit OR rerun OR reject"

    execution = execute_gate_selection(
        gate.bundle_path,
        ["edit"],
        {"edited_output": {"artifact": "fixed.json"}},
        source="test",
    )
    result = _translate_workflow_hitl_response(execution.response)
    assert result.action == "edit"
    assert result.edited_output == {"artifact": "fixed.json"}


def test_workflow_hitl_execution_failure_is_actionable_for_requester(
    hitl_gate_home: Path,
) -> None:
    spec = _workflow_hitl_gate_spec(
        step_name="review",
        step_type="agent",
        output={"answer": 42},
        workflow_name="demo",
        artifacts_dir=str(hitl_gate_home / "artifacts"),
        has_output=True,
        output_types=None,
        timeout_seconds=60,
    )
    spec["request_id"] = "workflow-hitl-failed"
    for resource in spec["resources"]:
        if resource["path"] == "commands/accept":
            resource["content"] = (
                "#!/usr/bin/env python3\n"
                "import json, sys\n"
                "json.load(sys.stdin)\n"
                "sys.stderr.write('workflow stderr stays in the report')\n"
                "sys.exit(6)\n"
            )
            break
    gate = create_gate(spec)

    with pytest.raises(GateError) as exc_info:
        execute_gate_selection(gate.bundle_path, ["accept"], {}, source="test")

    assert exc_info.value.code == "command_failed"
    result = wait_for_workflow_hitl_gate(gate.bundle_path)
    assert result.action == "reject"
    assert result.approved is False
    assert result.feedback is not None
    assert "Workflow HITL execution failed" in result.feedback
    assert "command: command_failed" in result.feedback
    assert "error report:" in result.feedback
    assert (
        "resume: sase gate answer --kind hitl --id workflow-hitl-failed "
        "--option accept --resume"
    ) in result.feedback
    assert (
        "restart: sase gate answer --kind hitl --id workflow-hitl-failed "
        "--option accept --restart"
    ) in result.feedback
    assert (
        "cancel: sase gate cancel --kind hitl --id workflow-hitl-failed"
        in result.feedback
    )
    assert "workflow stderr" not in result.feedback

    [failure] = [
        notification
        for notification in load_notifications()
        if notification.action == GATE_EXECUTION_FAILED_ACTION
    ]
    assert failure.tags == ["gate", "execution", "error"]
    assert failure.action_data["request_kind"] == "hitl"
    assert failure.action_data["stage"] == "command"
    assert failure.action_data["code"] == "command_failed"


def test_hitl_shell_maps_answered_cancelled_and_timeout_outcomes() -> None:
    raw = _workflow_hitl_gate_spec(
        step_name="review",
        step_type="agent",
        output={"answer": 42},
        workflow_name="demo",
        artifacts_dir="/tmp/artifacts",
        has_output=True,
        output_types=None,
        timeout_seconds=60,
    )
    option_ids = tuple(str(option["id"]) for option in raw["options"])
    raw["shell"] = _workflow_hitl_shell_spec(
        step_name="review",
        step_type="agent",
        workflow_name="demo",
        option_ids=option_ids,
    )

    spec = GateSpec.from_mapping(raw)
    assert spec.shell is not None
    envelope = {
        "shell": spec.shell.to_dict(),
        "branches": [list(branch) for branch in spec.branches],
        "gate_timeout_seconds": spec.gate_timeout_seconds,
    }

    followup = resolve_gate_followup(
        envelope,
        gate_state="answered",
        response={"selected_option_ids": ["accept"]},
    )
    assert followup is not None
    assert followup.branch_key == "accept"
    assert "Continue workflow `demo`" in followup.prompt

    assert resolve_gate_branch_presentation(
        envelope,
        gate_state="stopped",
        response={},
    ) == ("HITL CANCELLED", "#FFAF00")
    assert resolve_gate_branch_presentation(
        envelope,
        gate_state="timeout",
        response={},
    ) == ("HITL TIMED OUT", "#FFAF00")
