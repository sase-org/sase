"""Workflow HITL producer coverage for the option-query contract."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from sase.notification_gates.executor import execute_gate_selection
from sase.notifications import pending_actions
from sase.xprompt.workflow_hitl_gate import (
    create_workflow_hitl_gate,
    _translate_workflow_hitl_response,
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
    assert envelope["schema_version"] == 2
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
