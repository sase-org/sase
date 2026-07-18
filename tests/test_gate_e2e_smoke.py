"""End-to-end smoke tests for gate query system across CLI, executor, and surfaces."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import pytest

from sase.main.gate_handler import handle_gate_command
from sase.notification_gates.executor import execute_gate_selection
from sase.notification_gates.models import GateError
from sase.notification_gates.service import create_gate
from sase.plan_gate import (
    PLAN_APPROVE_OPTION_ID,
    PLAN_COMMIT_OPTION_ID,
    PLAN_FEEDBACK_OPTION_ID,
    PLAN_REJECT_OPTION_ID,
    create_plan_approval_gate,
    translate_plan_gate_response,
)
from sase.notifications import pending_actions

from tests.plan_validation_helpers import VALID_EPIC_PLAN, VALID_TALE_PLAN


@pytest.fixture()
def gate_home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
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
    monkeypatch.delenv("CLAUDE_PROJECT_DIR", raising=False)
    monkeypatch.delenv("SASE_ARTIFACTS_DIR", raising=False)
    store._LOAD_CACHE.clear()
    return tmp_path


def _write_plan(root: Path, name: str, content: str) -> Path:
    path = root / name
    path.write_text(content, encoding="utf-8")
    return path


def test_e2e_custom_gate_with_restart_verify_reject_query(
    gate_home: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Exercise a custom gate end-to-end: create, resolve with partial selection, check output."""
    spec = {
        "schema_version": 3,
        "request_id": "custom-restart",
        "kind": "custom",
        "producer": {"agent": "smoke-test"},
        "payload": {"operation": "restart"},
        "presentation": {
            "icon": "🔄",
            "sender": "system-manager",
            "notes": ["Verify restart sequence"],
        },
        "query": "(restart AND verify) OR reject",
        "primary_branch": ["restart", "verify"],
        "options": [
            {
                "id": "restart",
                "label": "Restart service",
                "icon": "🔄",
                "command": {"argv": ["commands/restart"]},
                "input_schema": {"type": "object"},
                "result_schema": {
                    "type": "object",
                    "required": ["status"],
                    "properties": {"status": {"const": "ok"}},
                },
            },
            {
                "id": "verify",
                "label": "Verify health after restart",
                "icon": "✅",
                "default_selected": True,
                "command": {"argv": ["commands/verify"]},
                "input_schema": {"type": "object"},
                "result_schema": {
                    "type": "object",
                    "required": ["status"],
                    "properties": {"status": {"const": "ok"}},
                },
            },
            {
                "id": "reject",
                "label": "Reject restart",
                "icon": "❌",
                "command": {"argv": ["commands/reject"]},
                "input_schema": {"type": "object"},
                "result_schema": {
                    "type": "object",
                    "required": ["status"],
                    "properties": {"status": {"const": "ok"}},
                },
            },
        ],
        "groups": [
            {
                "options": ["restart", "verify"],
                "label": "Proceed with restart",
                "icon": "🔄",
            }
        ],
        "resources": [
            {
                "path": "commands/restart",
                "role": "command",
                "content": (
                    "#!/usr/bin/env python3\n"
                    "import json, sys\n"
                    "json.load(sys.stdin)\n"
                    "print(json.dumps({'status': 'ok'}))\n"
                ),
            },
            {
                "path": "commands/verify",
                "role": "command",
                "content": (
                    "#!/usr/bin/env python3\n"
                    "import json, sys\n"
                    "data = json.load(sys.stdin)\n"
                    "print(json.dumps({'status': 'ok', 'health': 'green'}))\n"
                ),
            },
            {
                "path": "commands/reject",
                "role": "command",
                "content": (
                    "#!/usr/bin/env python3\n"
                    "import json, sys\n"
                    "json.load(sys.stdin)\n"
                    "print(json.dumps({'status': 'ok', 'reason': 'rejected'}))\n"
                ),
            },
        ],
        "auto": False,
    }

    result = create_gate(spec)

    request = json.loads(result.request_path.read_text(encoding="utf-8"))
    assert request["query"] == "(restart AND verify) OR reject"
    assert request["branches"] == [["restart", "verify"], ["reject"]]

    execution = execute_gate_selection(
        result.bundle_path,
        ["restart", "verify"],
    )
    assert execution.response["selected_option_ids"] == ["restart", "verify"]

    args = argparse.Namespace(
        gate_subcommand="wait",
        id="custom-restart",
        kind="custom",
        json=True,
        timeout=None,
    )

    with pytest.raises(SystemExit) as excinfo:
        handle_gate_command(args)

    assert excinfo.value.code == 0
    output = json.loads(capsys.readouterr().out)
    assert output["status"] == "answered"
    assert output["selected_option_ids"] == ["restart", "verify"]


def test_e2e_tale_plan_gate_structure_and_branches(gate_home: Path) -> None:
    """Verify tale plan gate has correct branches, group submit, and runner protocol."""
    tale_path = _write_plan(gate_home, "tale.md", VALID_TALE_PLAN)
    result = create_plan_approval_gate(
        tale_path,
        "e2e-tale-request",
        agent_name="smoke.test",
    )

    request = json.loads(result.request_path.read_text(encoding="utf-8"))

    assert request["query"] == "(approve AND commit) OR reject OR feedback"
    assert request["branches"] == [
        [PLAN_APPROVE_OPTION_ID, PLAN_COMMIT_OPTION_ID],
        [PLAN_REJECT_OPTION_ID],
        [PLAN_FEEDBACK_OPTION_ID],
    ]

    options = {opt["id"]: opt for opt in request["options"]}
    assert set(options.keys()) == {
        PLAN_APPROVE_OPTION_ID,
        PLAN_COMMIT_OPTION_ID,
        PLAN_REJECT_OPTION_ID,
        PLAN_FEEDBACK_OPTION_ID,
    }

    approve_opt = options[PLAN_APPROVE_OPTION_ID]
    commit_opt = options[PLAN_COMMIT_OPTION_ID]
    assert approve_opt["default_selected"] is True
    assert commit_opt["default_selected"] is True
    assert approve_opt["label"] == "Launch coder agent"
    assert approve_opt["icon"] == "🚀"
    assert commit_opt["label"] == "Commit plan file to the plans sidecar"

    groups = request["groups"]
    assert len(groups) == 1
    assert groups[0]["options"] == [PLAN_APPROVE_OPTION_ID, PLAN_COMMIT_OPTION_ID]
    assert groups[0]["label"] == "Tale"
    assert groups[0]["icon"] == "✅"

    exec_approve_commit = execute_gate_selection(
        result.bundle_path,
        [PLAN_APPROVE_OPTION_ID, PLAN_COMMIT_OPTION_ID],
    )
    runner_proto = translate_plan_gate_response(
        result.bundle_path,
        exec_approve_commit.response,
    )
    assert runner_proto["action"] == "approve"
    assert runner_proto["run_coder"] is True
    assert runner_proto["commit_plan"] is True


def test_e2e_epic_plan_retains_single_approve_control(gate_home: Path) -> None:
    """Verify the Epic singleton keeps its stable approve protocol behavior."""
    epic_path = _write_plan(gate_home, "epic.md", VALID_EPIC_PLAN)
    result = create_plan_approval_gate(epic_path, "e2e-epic-request")

    request = json.loads(result.request_path.read_text(encoding="utf-8"))
    options = {option["id"]: option for option in request["options"]}

    assert request["query"] == "approve OR reject OR feedback"
    assert request["groups"] == []
    assert options[PLAN_APPROVE_OPTION_ID]["label"] == "Epic"
    assert options[PLAN_APPROVE_OPTION_ID]["icon"] == "✅"

    execution = execute_gate_selection(
        result.bundle_path,
        [PLAN_APPROVE_OPTION_ID],
        {"epic_launch_mode": "foreground"},
    )
    assert execution.response["selected_option_ids"] == [PLAN_APPROVE_OPTION_ID]
    assert execution.response["input"] == {"epic_launch_mode": "foreground"}
    runner_proto = translate_plan_gate_response(result.bundle_path, execution.response)
    assert runner_proto["action"] == "epic"
    assert runner_proto["run_coder"] is True
    assert runner_proto["commit_plan"] is True


def test_e2e_v1_gate_request_rejected_with_guidance(gate_home: Path) -> None:
    """Confirm creation rejects a v1-shaped request with helpful error message."""
    v1_spec = {
        "schema_version": 1,
        "request_id": "v1-gate",
        "kind": "custom",
        "producer": {"agent": "old-code"},
        "payload": {"action": "approve"},
        "presentation": {"sender": "legacy"},
        "choices": [
            {
                "id": "approve",
                "label": "Approve",
                "command": {"argv": ["commands/approve"]},
            }
        ],
        "resources": [],
    }

    with pytest.raises(GateError) as exc_info:
        create_gate(v1_spec)

    error = exc_info.value
    assert error.code == "unsupported_schema"
