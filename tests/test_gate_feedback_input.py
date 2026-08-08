"""One feedback-to-input rule, exercised through the shared executor."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from sase.notification_gates.executor import execute_gate_selection
from sase.notification_gates.feedback_input import apply_feedback_input
from sase.notification_gates.models import GateError, GateOption
from sase.notification_gates.service import create_gate

_ECHO_COMMAND = (
    "#!/usr/bin/env python3\n"
    "import json, sys\n"
    "print(json.dumps({'status': 'ok', 'input': json.load(sys.stdin)}))\n"
)


def _note_gate_spec(
    *,
    input_schema: dict[str, Any],
    feedback: str,
    request_id: str = "feedback-input-request",
) -> dict[str, object]:
    return {
        "schema_version": 3,
        "request_id": request_id,
        "kind": "custom",
        "producer": {"agent": "test"},
        "payload": {},
        "presentation": {
            "icon": "🛡️",
            "title": "Review this",
            "sender": "test",
            "notes": ["Review this"],
        },
        "query": "proceed",
        "primary_branch": ["proceed"],
        "options": [
            {
                "id": "proceed",
                "label": "Proceed",
                "command": {"argv": ["commands/proceed"]},
                "input_schema": input_schema,
                "result_schema": {
                    "type": "object",
                    "required": ["status"],
                    "properties": {"status": {"const": "ok"}},
                    "additionalProperties": True,
                },
                "feedback": feedback,
            }
        ],
        "resources": [
            {
                "path": "commands/proceed",
                "role": "command",
                "content": _ECHO_COMMAND,
            }
        ],
    }


def _declaring_option_ids(options: list[dict[str, Any]]) -> set[str]:
    """The option ids the shared rule would hand the reviewer's note."""
    parsed = [
        GateOption.from_mapping(option, index) for index, option in enumerate(options)
    ]
    injected = apply_feedback_input(
        parsed, {option.id: {} for option in parsed}, "a note"
    )
    return {option_id for option_id, value in injected.items() if value}


def _submitted_input(response: dict[str, Any]) -> dict[str, Any]:
    [entry] = response["option_results"]
    result: dict[str, Any] = entry["result"]["input"]
    return result


def test_declared_optional_feedback_property_reaches_the_command(
    gate_home: Path,
) -> None:
    result = create_gate(
        _note_gate_spec(
            input_schema={
                "type": "object",
                "properties": {"feedback": {"type": "string"}},
                "additionalProperties": False,
            },
            feedback="optional",
        )
    )

    execution = execute_gate_selection(
        result.bundle_path,
        ["proceed"],
        feedback="  Ship it carefully  ",
    )

    assert _submitted_input(execution.response) == {"feedback": "Ship it carefully"}
    assert execution.response["feedback"] == "Ship it carefully"


def test_undeclared_feedback_property_leaves_the_command_input_empty(
    gate_home: Path,
) -> None:
    result = create_gate(
        _note_gate_spec(
            input_schema={"type": "object", "additionalProperties": False},
            feedback="optional",
        )
    )

    execution = execute_gate_selection(
        result.bundle_path,
        ["proceed"],
        feedback="Ship it carefully",
    )

    assert _submitted_input(execution.response) == {}
    assert execution.response["feedback"] == "Ship it carefully"


def test_required_feedback_is_rejected_before_any_command_runs(
    gate_home: Path,
) -> None:
    result = create_gate(
        _note_gate_spec(
            input_schema={
                "type": "object",
                "required": ["feedback"],
                "properties": {"feedback": {"type": "string", "minLength": 1}},
                "additionalProperties": False,
            },
            feedback="required",
        )
    )

    started: list[str] = []
    with pytest.raises(GateError) as missing:
        execute_gate_selection(
            result.bundle_path,
            ["proceed"],
            on_command_start=lambda _kind, option_id, _label, _argv: started.append(
                option_id
            ),
        )

    assert missing.value.code == "feedback_required"
    assert started == []
    assert not result.response_path.exists()


def test_the_note_is_injected_only_where_the_schema_declares_it(
    gate_home: Path,
) -> None:
    spec = _note_gate_spec(
        input_schema={
            "type": "object",
            "properties": {"feedback": {"type": "string"}},
            "additionalProperties": False,
        },
        feedback="optional",
    )
    options = list(spec["options"])  # type: ignore[call-overload]
    options.append(
        {
            "id": "record",
            "label": "Record",
            "command": {"argv": ["commands/record"]},
            "input_schema": {"type": "object", "additionalProperties": False},
            "result_schema": {
                "type": "object",
                "required": ["status"],
                "properties": {"status": {"const": "ok"}},
                "additionalProperties": True,
            },
        }
    )
    spec["options"] = options
    spec["query"] = "(proceed AND record)"
    spec["primary_branch"] = ["proceed", "record"]
    resources = list(spec["resources"])  # type: ignore[call-overload]
    resources.append(
        {"path": "commands/record", "role": "command", "content": _ECHO_COMMAND}
    )
    spec["resources"] = resources

    result = create_gate(spec)
    execution = execute_gate_selection(
        result.bundle_path,
        ["proceed", "record"],
        feedback="Ship it carefully",
    )

    by_id = {
        entry["id"]: entry["result"]["input"]
        for entry in execution.response["option_results"]
    }
    assert by_id == {"proceed": {"feedback": "Ship it carefully"}, "record": {}}


def test_hitl_feedback_option_keeps_its_closed_empty_input(
    gate_home: Path,
) -> None:
    """The audited built-in that would break if the note were always injected."""
    from sase.xprompt.workflow_hitl_gate import create_workflow_hitl_gate

    gate = create_workflow_hitl_gate(
        step_name="review",
        step_type="agent",
        output={"answer": 42},
        workflow_name="demo",
        artifacts_dir=str(gate_home / "artifacts"),
        has_output=True,
        output_types=None,
        timeout_seconds=60,
    )

    envelope = json.loads(gate.request_path.read_text(encoding="utf-8"))
    schemas = {option["id"]: option["input_schema"] for option in envelope["options"]}
    assert "feedback" not in schemas["feedback"].get("properties", {})

    execution = execute_gate_selection(
        gate.bundle_path,
        ["feedback"],
        feedback="Please rework the summary",
    )

    assert execution.response["feedback"] == "Please rework the summary"


def test_launch_gate_reject_option_declares_the_property() -> None:
    """The audited built-in the rule must keep working for.

    The launch gate used to buy its note with a third option id; the note now
    reaches ``reject``'s command because that option declares the property.
    """
    from sase.agent.launch_request_gate import launch_gate_spec

    spec = launch_gate_spec(
        {"request_id": "launch-1", "prompt": "do the thing", "agents": []},
        preview="preview",
        source_surface="ace",
        slot_count=1,
    )
    assert _declaring_option_ids(spec["options"]) == {"reject"}


def test_task_triage_options_declare_the_property_only_where_collected() -> None:
    """The audited built-ins whose commands assert an empty input.

    Only ``snooze`` declares inputs, so only its compiled schema carries the
    optional ``feedback`` property; ``launch`` and ``close`` keep the closed
    empty input their commands assert.
    """
    from sase.bead._task_gate_spec import build_task_triage_gate_spec

    spec = build_task_triage_gate_spec(
        request_id="triage-1",
        bead_id="sase-1",
        project="sase",
        title="Do the thing",
    )
    assert _declaring_option_ids(spec["options"]) == {"snooze"}


def test_apply_feedback_input_passes_non_object_values_through() -> None:
    option = GateOption.from_mapping(
        {
            "id": "proceed",
            "label": "Proceed",
            "command": {"argv": ["commands/proceed"]},
            "input_schema": {"properties": {"feedback": {"type": "string"}}},
        },
        0,
    )

    assert apply_feedback_input([option], {"proceed": "raw"}, "note") == {
        "proceed": "raw"
    }
    assert apply_feedback_input([option], {"proceed": {}}, None) == {"proceed": {}}
    assert apply_feedback_input([option], {}, "note") == {}
