"""``sase gate wait --json`` -- what a gate asked for and what it received."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

import pytest

from sase.main.gate_handler import handle_gate_command
from sase.main.parser_gate import register_gate_parser
from sase.notification_gates.executor import cancel_gate, execute_gate_selection
from sase.notification_gates.models import GateError
from sase.notification_gates.operations import execute_gate_operation
from sase.notification_gates.service import create_gate

_ANSWER_COMMAND = (
    "#!/usr/bin/env python3\n"
    "import json, sys\n"
    "print(json.dumps({'status': 'ok', 'received': json.load(sys.stdin)}))\n"
)

_ACTION_COMMAND = (
    "#!/usr/bin/env python3\n"
    "import json, sys\n"
    "json.load(sys.stdin)\n"
    "print(json.dumps({'summary': '3 files changed', 'body': 'diff body'}))\n"
)

_FAILING_ACTION_COMMAND = (
    "#!/usr/bin/env python3\nimport sys\nsys.stderr.write('boom')\nsys.exit(3)\n"
)


def _spec(request_id: str) -> dict[str, Any]:
    return {
        "schema_version": 3,
        "request_id": request_id,
        "kind": "custom",
        "producer": {"agent": "test"},
        "payload": {},
        "presentation": {"icon": "🚀", "title": "Deploy", "notes": ["Deploy"]},
        "query": "deploy",
        "primary_branch": ["deploy"],
        "options": [
            {
                "id": "deploy",
                "label": "Deploy",
                "command": {"argv": ["commands/deploy"]},
                "inputs": [
                    {
                        "id": "target_env",
                        "label": "Target env",
                        "type": "word",
                        "required": True,
                    }
                ],
            }
        ],
        "operations": [
            {
                "id": "show_diff",
                "kind": "run_command",
                "command": {"argv": ["commands/show_diff"]},
                "result_schema": {"type": "object"},
            },
            {
                "id": "boom",
                "kind": "run_command",
                "command": {"argv": ["commands/boom"]},
                "result_schema": {"type": "object"},
            },
        ],
        "resources": [
            {"path": "commands/deploy", "role": "command", "content": _ANSWER_COMMAND},
            {
                "path": "commands/show_diff",
                "role": "command",
                "content": _ACTION_COMMAND,
            },
            {
                "path": "commands/boom",
                "role": "command",
                "content": _FAILING_ACTION_COMMAND,
            },
        ],
        "auto": False,
    }


def _wait_json(
    gate_home: Path, capsys: pytest.CaptureFixture[str], request_id: str
) -> tuple[int, Any]:
    del gate_home
    parser = argparse.ArgumentParser(prog="sase")
    register_gate_parser(parser.add_subparsers(dest="command"))
    args = parser.parse_args(
        ["gate", "wait", "--id", request_id, "--kind", "custom", "--json"]
    )
    with pytest.raises(SystemExit) as excinfo:
        handle_gate_command(args)
    code = int(excinfo.value.code or 0)
    payload = json.loads(capsys.readouterr().out)
    return code, payload


def test_answered_gate_reports_input_option_inputs_and_operations(
    gate_home: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """New keys are additive; old keys keep their meaning and position."""
    request_id = "wait-answered"
    gate = create_gate(_spec(request_id))
    execute_gate_operation(gate.bundle_path, "show_diff")
    execute_gate_selection(
        gate.bundle_path,
        ["deploy"],
        option_inputs={"deploy": {"target_env": "staging"}},
        feedback="ship it",
    )

    code, payload = _wait_json(gate_home, capsys, request_id)

    assert code == 0
    assert list(payload.keys())[:4] == [
        "status",
        "selected_option_ids",
        "feedback",
        "response_path",
    ]
    assert payload["status"] == "answered"
    assert payload["selected_option_ids"] == ["deploy"]
    assert payload["feedback"] == "ship it"
    assert payload["option_inputs"] == {
        "deploy": {"target_env": "staging", "feedback": "ship it"}
    }
    assert payload["input"] == {}
    assert [result["id"] for result in payload["option_results"]] == ["deploy"]
    assert len(payload["operations"]) == 1
    operation = payload["operations"][0]
    assert operation["operation_id"] == "show_diff"
    assert operation["ok"] is True
    assert operation["code"] is None
    assert isinstance(operation["at_unix"], float)


def test_failed_action_is_reported_alongside_a_successful_one(
    gate_home: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    request_id = "wait-failed-action"
    gate = create_gate(_spec(request_id))
    execute_gate_operation(gate.bundle_path, "show_diff")
    with pytest.raises(GateError):
        execute_gate_operation(gate.bundle_path, "boom")
    execute_gate_selection(
        gate.bundle_path, ["deploy"], option_inputs={"deploy": {"target_env": "prod"}}
    )

    _code, payload = _wait_json(gate_home, capsys, request_id)

    operations = {op["operation_id"]: op for op in payload["operations"]}
    assert operations["show_diff"]["ok"] is True
    assert operations["boom"]["ok"] is False
    assert operations["boom"]["code"] == "command_failed"


def test_cancelled_gate_has_empty_answer_fields_but_still_reports_operations(
    gate_home: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    request_id = "wait-cancelled"
    gate = create_gate(_spec(request_id))
    execute_gate_operation(gate.bundle_path, "show_diff")
    cancel_gate(gate.bundle_path, reason="requester_cancelled")

    code, payload = _wait_json(gate_home, capsys, request_id)

    assert code == 3
    assert payload["status"] == "cancelled"
    assert payload["input"] is None
    assert payload["option_inputs"] == {}
    assert payload["option_results"] == []
    assert [op["operation_id"] for op in payload["operations"]] == ["show_diff"]


def test_agent_gate_wait_refuses_shell_gate(
    gate_home: Path,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    request_id = "wait-shell"
    raw = _spec(request_id)
    raw["shell"] = {}
    create_gate(raw)
    monkeypatch.setenv("SASE_AGENT", "1")

    parser = argparse.ArgumentParser(prog="sase")
    register_gate_parser(parser.add_subparsers(dest="command"))
    args = parser.parse_args(
        ["gate", "wait", "--id", request_id, "--kind", "custom", "--json"]
    )

    with pytest.raises(SystemExit) as excinfo:
        handle_gate_command(args)

    assert int(excinfo.value.code or 0) == 1
    captured = capsys.readouterr()
    assert captured.out == ""
    assert "shell gate cannot be waited on from inside an agent" in captured.err
