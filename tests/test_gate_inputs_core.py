"""Declarative per-option gate ``inputs`` and per-option submission coverage."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

import pytest

from sase.notification_gates.branches import GateBranchData
from sase.notification_gates.executor import execute_gate_selection
from sase.notification_gates.model_inputs import (
    GateInputField,
    compile_gate_input_schema,
)
from sase.notification_gates.model_validation import first_schema_error
from sase.notification_gates.models import GateError, GateOption
from sase.notification_gates.service import create_gate
from sase.xprompt.models import (
    InputArg,
    InputChoice,
    InputType,
    XPromptValidationError,
)
from tests._notification_gates_fixtures import custom_gate_spec

# -- compile_gate_input_schema -----------------------------------------------


@pytest.mark.parametrize(
    ("input_type", "choices", "expected_fragment"),
    [
        (
            InputType.WORD,
            (),
            {"type": "string", "minLength": 1, "pattern": r"^\S+(?![\s\S])"},
        ),
        (
            InputType.AGENT,
            (),
            {"type": "string", "minLength": 1, "pattern": r"^\S+(?![\s\S])"},
        ),
        (InputType.LINE, (), {"type": "string", "pattern": r"^[^\n]*(?![\s\S])"}),
        (InputType.TEXT, (), {"type": "string"}),
        (
            InputType.PATH,
            (),
            {"type": "string", "minLength": 1, "pattern": r"^[^\n]*(?![\s\S])"},
        ),
        (InputType.INT, (), {"type": "integer"}),
        (InputType.FLOAT, (), {"type": "number"}),
        (InputType.BOOL, (), {"type": "boolean"}),
        (
            InputType.ENUM,
            (InputChoice(value="fast"), InputChoice(value="slow")),
            {"enum": ["fast", "slow"]},
        ),
    ],
)
def test_compile_gate_input_schema_covers_every_type(
    input_type: InputType,
    choices: tuple[InputChoice, ...],
    expected_fragment: dict,
) -> None:
    field = GateInputField(id="value", label="Value", type=input_type, choices=choices)
    schema = compile_gate_input_schema((field,), feedback_mode="disabled")

    assert schema["properties"]["value"] == expected_fragment
    assert schema["required"] == []
    assert schema["additionalProperties"] is False
    assert schema["$schema"] == "https://json-schema.org/draft/2020-12/schema"


def test_compile_gate_input_schema_wraps_repeatable_fragment_in_array() -> None:
    field = GateInputField(
        id="tags", label="Tags", type=InputType.WORD, repeatable=True
    )
    schema = compile_gate_input_schema((field,), feedback_mode="disabled")

    assert schema["properties"]["tags"] == {
        "type": "array",
        "items": {"type": "string", "minLength": 1, "pattern": r"^\S+(?![\s\S])"},
    }


@pytest.mark.parametrize(
    "input_type",
    [InputType.WORD, InputType.AGENT, InputType.LINE, InputType.PATH],
)
@pytest.mark.parametrize("value", ["ab\n", "ab\n\n", "ab", "a b"])
def test_compiled_pattern_and_validate_and_convert_agree(
    input_type: InputType, value: str
) -> None:
    """The schema layer and the typed layer must reach the same verdict.

    Python's ``re`` lets ``$`` match before a trailing newline, so the original
    ``^\\S+$`` accepted ``"ab\\n"`` through ``--option-input``, the ACE raw
    editor, and the mobile bridge while a typed ACE form refused it.
    """
    field = GateInputField(id="value", label="Value", type=input_type)
    schema = compile_gate_input_schema((field,), feedback_mode="disabled")
    arg = InputArg(name="value", type=input_type)

    schema_accepts = first_schema_error({"value": value}, schema) is None
    try:
        arg.validate_and_convert(value)
    except XPromptValidationError:
        typed_accepts = False
    else:
        typed_accepts = True

    assert schema_accepts is typed_accepts


def test_compile_gate_input_schema_collects_required_ids() -> None:
    fields = (
        GateInputField(id="a", label="A", type=InputType.WORD, required=True),
        GateInputField(id="b", label="B", type=InputType.WORD, required=False),
    )
    schema = compile_gate_input_schema(fields, feedback_mode="disabled")

    assert schema["required"] == ["a"]


@pytest.mark.parametrize("feedback_mode", ["optional", "required"])
def test_compile_gate_input_schema_injects_feedback_property(
    feedback_mode: str,
) -> None:
    schema = compile_gate_input_schema((), feedback_mode=feedback_mode)  # type: ignore[arg-type]

    assert schema["properties"]["feedback"] == {"type": "string"}
    assert "feedback" not in schema["required"]


def test_compile_gate_input_schema_omits_feedback_when_disabled() -> None:
    schema = compile_gate_input_schema((), feedback_mode="disabled")

    assert "feedback" not in schema["properties"]


def test_declared_feedback_field_suppresses_automatic_injection() -> None:
    field = GateInputField(
        id="feedback",
        label="Feedback",
        type=InputType.ENUM,
        choices=(InputChoice(value="thumbs_up"), InputChoice(value="thumbs_down")),
    )
    schema = compile_gate_input_schema((field,), feedback_mode="required")

    assert schema["properties"]["feedback"] == {"enum": ["thumbs_up", "thumbs_down"]}


# -- GateOption.inputs / input_schema conflict -------------------------------


def test_inputs_with_a_differing_raw_input_schema_raises_conflict() -> None:
    with pytest.raises(GateError) as excinfo:
        GateOption.from_mapping(
            {
                "id": "approve",
                "label": "Approve",
                "command": {"argv": ["commands/approve"]},
                "inputs": [{"id": "mode", "label": "Mode", "type": "word"}],
                "input_schema": {
                    "type": "object",
                    "properties": {},
                    "additionalProperties": True,
                },
            },
            0,
        )
    assert excinfo.value.code == "conflicting_input_declaration"


def test_gate_option_inputs_survive_envelope_round_trip(gate_home: Path) -> None:
    spec: dict[str, Any] = custom_gate_spec(request_id="inputs-round-trip")
    spec["options"][0].pop("input_schema", None)
    spec["options"][0]["inputs"] = [
        {"id": "coder_prompt", "label": "Coder prompt", "type": "text"},
        {
            "id": "mode",
            "label": "Mode",
            "type": "enum",
            "choices": ["fast", "slow"],
            "required": True,
        },
    ]
    result = create_gate(spec)
    envelope = json.loads(result.request_path.read_text(encoding="utf-8"))

    reparsed_option = GateOption.from_mapping(envelope["options"][0], 0)
    assert [field.id for field in reparsed_option.inputs] == ["coder_prompt", "mode"]
    mode_field = reparsed_option.inputs[1]
    assert mode_field.choices == (
        InputChoice(value="fast"),
        InputChoice(value="slow"),
    )
    assert reparsed_option.input_schema == compile_gate_input_schema(
        reparsed_option.inputs, feedback_mode=reparsed_option.feedback
    )

    branch_data = GateBranchData.from_envelope(envelope)
    round_tripped = next(
        option for option in branch_data.options if option.id == "proceed"
    )
    assert round_tripped.inputs == reparsed_option.inputs
    assert round_tripped.input_schema == reparsed_option.input_schema


# -- per-option submission ----------------------------------------------------

_ECHO_RECEIVED_COMMAND = (
    "#!/usr/bin/env python3\n"
    "import json, sys\n"
    "value = json.load(sys.stdin)\n"
    "print(json.dumps({'status': 'ok', 'received': value}))\n"
)

_RESULT_SCHEMA = {
    "type": "object",
    "required": ["status"],
    "properties": {"status": {"const": "ok"}},
}


def _and_pair_spec(*, request_id: str) -> dict[str, object]:
    return {
        "schema_version": 3,
        "request_id": request_id,
        "kind": "custom",
        "producer": {"agent": "test"},
        "payload": {},
        "presentation": {
            "icon": "🛡️",
            "title": "Confirm guarded work",
            "sender": "safety-check",
            "notes": ["Confirm guarded work"],
        },
        "query": "(a AND b)",
        "primary_branch": ["a", "b"],
        "options": [
            {
                "id": "a",
                "label": "Option A",
                "command": {"argv": ["commands/a"]},
                "inputs": [
                    {
                        "id": "value_a",
                        "label": "A value",
                        "type": "word",
                        "required": True,
                    }
                ],
                "result_schema": _RESULT_SCHEMA,
            },
            {
                "id": "b",
                "label": "Option B",
                "command": {"argv": ["commands/b"]},
                "inputs": [
                    {
                        "id": "value_b",
                        "label": "B value",
                        "type": "word",
                        "required": True,
                    }
                ],
                "result_schema": _RESULT_SCHEMA,
            },
        ],
        "groups": [{"options": ["a", "b"], "label": "Both"}],
        "resources": [
            {
                "path": "commands/a",
                "role": "command",
                "content": _ECHO_RECEIVED_COMMAND,
            },
            {
                "path": "commands/b",
                "role": "command",
                "content": _ECHO_RECEIVED_COMMAND,
            },
        ],
        "auto": False,
    }


def test_per_option_submission_delivers_distinct_values_to_and_members(
    gate_home: Path,
) -> None:
    result = create_gate(_and_pair_spec(request_id="per-option-submission"))

    execution = execute_gate_selection(
        result.bundle_path,
        ["a", "b"],
        option_inputs={"a": {"value_a": "fast"}, "b": {"value_b": "slow"}},
    )

    results_by_id = {
        entry["id"]: entry["result"] for entry in execution.response["option_results"]
    }
    assert results_by_id["a"]["received"] == {"value_a": "fast"}
    assert results_by_id["b"]["received"] == {"value_b": "slow"}
    assert execution.response["option_inputs"] == {
        "a": {"value_a": "fast"},
        "b": {"value_b": "slow"},
    }
    assert execution.response["input"] == {}


def test_legacy_shared_input_data_is_unchanged_and_mirrors_into_option_inputs(
    gate_home: Path,
) -> None:
    result = create_gate(custom_gate_spec(request_id="legacy-shared"))

    execution = execute_gate_selection(
        result.bundle_path, ["proceed", "audit"], {"reviewed": True}
    )

    assert execution.response["input"] == {"reviewed": True}
    assert execution.response["option_inputs"] == {
        "proceed": {"reviewed": True},
        "audit": {"reviewed": True},
    }


def test_conflicting_and_unknown_option_submissions_leave_gate_pending(
    gate_home: Path,
) -> None:
    result = create_gate(custom_gate_spec(request_id="conflict-and-unknown"))

    with pytest.raises(GateError) as conflict:
        execute_gate_selection(
            result.bundle_path,
            ["proceed"],
            {"reviewed": True},
            option_inputs={"proceed": {"reviewed": True}},
        )
    assert conflict.value.code == "conflicting_input"
    assert not result.response_path.exists()

    with pytest.raises(GateError) as unknown:
        execute_gate_selection(
            result.bundle_path,
            ["proceed"],
            option_inputs={"missing_option": {}},
        )
    assert unknown.value.code == "unknown_option"
    assert not result.response_path.exists()


def test_required_declared_field_missing_fails_schema_validation(
    gate_home: Path,
) -> None:
    spec: dict[str, Any] = custom_gate_spec(request_id="required-field")
    spec["options"][0].pop("input_schema", None)
    spec["options"][0]["inputs"] = [
        {"id": "reason", "label": "Reason", "type": "text", "required": True}
    ]
    result = create_gate(spec)

    with pytest.raises(GateError) as excinfo:
        execute_gate_selection(result.bundle_path, ["proceed", "audit"])
    assert excinfo.value.code == "schema_validation_failed"
    assert not result.response_path.exists()


def test_secret_input_field_reaches_stdin_but_is_redacted_in_response(
    gate_home: Path,
) -> None:
    echo_digest = (
        "#!/usr/bin/env python3\n"
        "import hashlib, json, sys\n"
        "value = json.load(sys.stdin)\n"
        "digest = hashlib.sha256(value['token'].encode()).hexdigest()\n"
        "print(json.dumps({'status': 'ok', 'digest': digest}))\n"
    )
    spec: dict[str, Any] = custom_gate_spec(request_id="secret-field")
    spec["options"][0].pop("input_schema", None)
    spec["options"][0]["inputs"] = [
        {
            "id": "token",
            "label": "Token",
            "type": "text",
            "required": True,
            "secret": True,
        }
    ]
    spec["resources"][0]["content"] = echo_digest
    result = create_gate(spec)

    execution = execute_gate_selection(
        result.bundle_path,
        ["proceed"],
        {"token": "shhh"},
    )

    [proceed_entry] = execution.response["option_results"]
    assert proceed_entry["result"]["digest"] == hashlib.sha256(b"shhh").hexdigest()
    assert execution.response["option_inputs"]["proceed"] == {
        "token": {"$redacted": True}
    }


def test_secret_echoed_by_a_command_is_redacted_out_of_both_audit_files(
    gate_home: Path,
) -> None:
    """Neither durable file may hold a submitted secret.

    ``response.json`` and ``journal.jsonl`` both store a completed option's
    result, and a command is free to echo its stdin back -- the conformance
    matrix's own echo command does. Redacting the secret out of
    ``option_inputs`` alone leaves it sitting in ``option_results`` one key
    over, in the very file the redaction exists to protect.
    """
    echo_input = (
        "#!/usr/bin/env python3\n"
        "import json, sys\n"
        "value = json.load(sys.stdin)\n"
        "print(json.dumps({'status': 'ok', 'input': value, "
        "'note': 'used ' + value['token'], "
        "'lookup': {'token-' + value['token']: 'matched', 'safe': 'kept'}}))\n"
    )
    spec: dict[str, Any] = custom_gate_spec(request_id="secret-journal")
    spec["options"][0].pop("input_schema", None)
    spec["options"][0]["inputs"] = [
        {
            "id": "token",
            "label": "Token",
            "type": "text",
            "required": True,
            "secret": True,
        },
        {"id": "reason", "label": "Reason", "type": "text"},
    ]
    spec["resources"][0]["content"] = echo_input
    result = create_gate(spec)

    execute_gate_selection(
        result.bundle_path,
        ["proceed"],
        {"token": "hunter2", "reason": "rotation"},
    )

    journal = (result.bundle_path / "journal.jsonl").read_text()
    response = (result.bundle_path / "response.json").read_text()
    assert "hunter2" not in journal
    assert "hunter2" not in response
    assert "rotation" in journal
    assert "rotation" in response
    [completed] = [
        json.loads(line)
        for line in journal.splitlines()
        if line.strip() and json.loads(line).get("event") == "option_completed"
    ]
    [recorded] = json.loads(response)["option_results"]
    for stored in (completed["result"], recorded["result"]):
        assert stored["input"]["token"] == {"$redacted": True}
        assert stored["input"]["reason"] == "rotation"
        assert stored["note"] == {"$redacted": True}
        assert stored["lookup"] == {"$redacted": True}
        assert stored["status"] == "ok"


def test_secret_echoed_by_a_failing_command_is_redacted_from_error_record(
    gate_home: Path,
) -> None:
    failing_echo = (
        "#!/usr/bin/env python3\n"
        "import json, sys\n"
        "value = json.load(sys.stdin)['token']\n"
        "print('stdout-' + value)\n"
        "sys.stderr.write('stderr-' + value)\n"
        "raise SystemExit(9)\n"
    )
    spec: dict[str, Any] = custom_gate_spec(request_id="secret-error")
    spec["options"][0].pop("input_schema", None)
    spec["options"][0]["inputs"] = [
        {
            "id": "token",
            "label": "Token",
            "type": "text",
            "required": True,
            "secret": True,
        }
    ]
    spec["resources"][0]["content"] = failing_echo
    result = create_gate(spec)

    with pytest.raises(GateError, match="command failed; output redacted") as exc_info:
        execute_gate_selection(
            result.bundle_path,
            ["proceed"],
            {"token": "hunter2"},
        )
    assert exc_info.value.code == "command_failed"

    [error_path] = (result.bundle_path / "errors").glob("*.json")
    error_text = error_path.read_text(encoding="utf-8")
    error = json.loads(error_text)
    assert "hunter2" not in error_text
    assert error["message"] == (
        "command failed; output redacted because it contained a submitted secret"
    )
    assert error["stdout"] == "<redacted>"
    assert error["stderr"] == "<redacted>"


def test_rejected_secret_input_is_redacted_from_error_record(gate_home: Path) -> None:
    spec: dict[str, Any] = custom_gate_spec(request_id="secret-rejection")
    spec["options"][0].pop("input_schema", None)
    spec["options"][0]["inputs"] = [
        {
            "id": "token",
            "label": "Token",
            "type": "word",
            "required": True,
            "secret": True,
        }
    ]
    result = create_gate(spec)

    with pytest.raises(GateError, match="<redacted>") as exc_info:
        execute_gate_selection(
            result.bundle_path,
            ["proceed"],
            {"token": "hunter two"},
        )
    assert exc_info.value.code == "schema_validation_failed"

    [error_path] = (result.bundle_path / "errors").glob("*.json")
    error_text = error_path.read_text(encoding="utf-8")
    error = json.loads(error_text)
    assert "hunter two" not in error_text
    assert error["message"] == "<redacted>"
