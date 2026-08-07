"""Creation-time answerability, dialect, and bounds coverage for custom gates."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from sase.notification_gates.executor import execute_gate_selection
from sase.notification_gates.model_validation import (
    JSON_SCHEMA_DIALECT,
    MAX_OBJECT_PROPERTIES,
    NO_INPUT_SCHEMA,
)
from sase.notification_gates.models import GateError, GateExecutionResult
from sase.notification_gates.service import create_gate
from tests._notification_gates_fixtures import custom_gate_spec

_ECHO_INPUT = (
    "#!/usr/bin/env python3\n"
    "import json, sys\n"
    "value = json.load(sys.stdin)\n"
    "print(json.dumps({'status': 'ok', 'input': value}))\n"
)


def _single_option_spec(
    *, request_id: str, option: dict[str, Any], command: str = _ECHO_INPUT
) -> dict[str, Any]:
    return {
        "schema_version": 3,
        "request_id": request_id,
        "kind": "custom",
        "producer": {"agent": "test"},
        "payload": {},
        "presentation": {
            "icon": "🛡️",
            "title": "Confirm guarded work",
            "notes": ["Confirm guarded work"],
        },
        "query": "proceed",
        "primary_branch": ["proceed"],
        "options": [{"id": "proceed", "label": "Proceed", **option}],
        "resources": [
            {"path": "commands/proceed", "role": "command", "content": command}
        ],
        "auto": False,
    }


def _proceed_option(**overrides: Any) -> dict[str, Any]:
    return {"command": {"argv": ["commands/proceed"]}, **overrides}


def _results(execution: GateExecutionResult) -> dict[str, Any]:
    return {
        entry["id"]: entry["result"] for entry in execution.response["option_results"]
    }


# -- answerability -----------------------------------------------------------


def test_required_property_without_a_declared_input_is_rejected_at_creation(
    gate_home: Path,
) -> None:
    spec = _single_option_spec(
        request_id="unanswerable",
        option=_proceed_option(
            input_schema={
                "type": "object",
                "required": ["target_env"],
                "properties": {"target_env": {"type": "string"}},
                "additionalProperties": False,
            }
        ),
    )

    with pytest.raises(GateError) as excinfo:
        create_gate(spec)

    assert excinfo.value.code == "unanswerable_option"
    assert excinfo.value.target == "options[0].input_schema"
    assert "'target_env'" in str(excinfo.value)
    assert "'inputs'" in str(excinfo.value)


def test_the_same_gate_declaring_the_field_under_inputs_is_answerable(
    gate_home: Path,
) -> None:
    spec = _single_option_spec(
        request_id="answerable",
        option=_proceed_option(
            inputs=[
                {
                    "id": "target_env",
                    "label": "Target environment",
                    "type": "line",
                    "required": True,
                }
            ]
        ),
    )

    result = create_gate(spec)
    execution = execute_gate_selection(
        result.bundle_path, ["proceed"], option_inputs={"proceed": {"target_env": "qa"}}
    )

    assert _results(execution) == {
        "proceed": {"status": "ok", "input": {"target_env": "qa"}}
    }


def test_a_required_feedback_property_is_answerable_only_when_feedback_is_enabled(
    gate_home: Path,
) -> None:
    schema = {
        "type": "object",
        "required": ["feedback"],
        "properties": {"feedback": {"type": "string"}},
        "additionalProperties": False,
    }

    with pytest.raises(GateError) as excinfo:
        create_gate(
            _single_option_spec(
                request_id="feedback-disabled",
                option=_proceed_option(input_schema=schema, feedback="disabled"),
            )
        )
    assert excinfo.value.code == "unanswerable_option"

    result = create_gate(
        _single_option_spec(
            request_id="feedback-optional",
            option=_proceed_option(input_schema=schema, feedback="optional"),
        )
    )
    execution = execute_gate_selection(
        result.bundle_path, ["proceed"], feedback="looks fine"
    )
    assert _results(execution)["proceed"]["input"] == {"feedback": "looks fine"}


def test_a_required_property_declaring_a_format_says_format_is_annotation_only(
    gate_home: Path,
) -> None:
    spec = _single_option_spec(
        request_id="format-required",
        option=_proceed_option(
            input_schema={
                "type": "object",
                "required": ["contact"],
                "properties": {"contact": {"type": "string", "format": "email"}},
            }
        ),
    )

    with pytest.raises(GateError) as excinfo:
        create_gate(spec)

    assert excinfo.value.code == "unanswerable_option"
    assert "annotation-only" in str(excinfo.value)


def test_a_declared_default_makes_an_otherwise_unanswerable_option_answerable(
    gate_home: Path,
) -> None:
    spec = _single_option_spec(
        request_id="defaulted",
        option=_proceed_option(
            inputs=[
                {
                    "id": "tier",
                    "label": "Tier",
                    "type": "enum",
                    "required": True,
                    "choices": ["gold", "silver"],
                    "default": "silver",
                }
            ]
        ),
    )

    result = create_gate(spec)
    envelope = json.loads(result.request_path.read_text(encoding="utf-8"))
    assert envelope["options"][0]["input_schema"]["required"] == ["tier"]


# -- omission means "no input" ----------------------------------------------


def test_an_omitted_input_schema_compiles_to_the_no_input_schema(
    gate_home: Path,
) -> None:
    result = create_gate(
        _single_option_spec(request_id="omitted", option=_proceed_option())
    )

    envelope = json.loads(result.request_path.read_text(encoding="utf-8"))
    assert envelope["options"][0]["input_schema"] == NO_INPUT_SCHEMA

    with pytest.raises(GateError) as excinfo:
        execute_gate_selection(
            result.bundle_path, ["proceed"], option_inputs={"proceed": {"extra": 1}}
        )
    assert excinfo.value.code == "schema_validation_failed"
    assert not result.response_path.exists()


def test_an_explicit_empty_input_schema_stays_permissive(gate_home: Path) -> None:
    result = create_gate(
        _single_option_spec(
            request_id="explicit-empty", option=_proceed_option(input_schema={})
        )
    )

    envelope = json.loads(result.request_path.read_text(encoding="utf-8"))
    assert envelope["options"][0]["input_schema"] == {"$schema": JSON_SCHEMA_DIALECT}

    execution = execute_gate_selection(
        result.bundle_path, ["proceed"], option_inputs={"proceed": {"anything": [1, 2]}}
    )
    assert _results(execution)["proceed"]["input"] == {"anything": [1, 2]}


# -- dialect -----------------------------------------------------------------


def test_a_non_2020_12_dialect_is_rejected(gate_home: Path) -> None:
    spec = _single_option_spec(
        request_id="wrong-dialect",
        option=_proceed_option(
            input_schema={
                "$schema": "http://json-schema.org/draft-07/schema#",
                "type": "object",
            }
        ),
    )

    with pytest.raises(GateError) as excinfo:
        create_gate(spec)

    assert excinfo.value.code == "unsupported_schema_dialect"
    assert JSON_SCHEMA_DIALECT in str(excinfo.value)


def test_every_stored_schema_is_stamped_with_the_pinned_dialect(
    gate_home: Path,
) -> None:
    result = create_gate(custom_gate_spec(request_id="stamped"))

    envelope = json.loads(result.request_path.read_text(encoding="utf-8"))
    for option in envelope["options"]:
        assert option["input_schema"]["$schema"] == JSON_SCHEMA_DIALECT
        assert option["result_schema"]["$schema"] == JSON_SCHEMA_DIALECT


# -- declared defaults -------------------------------------------------------


@pytest.mark.parametrize(
    ("input_field", "expected_fragment"),
    [
        ({"type": "int", "default": "seven"}, "int"),
        ({"type": "enum", "choices": ["a", "b"], "default": "c"}, "enum"),
        ({"type": "word", "default": "two words"}, "word"),
        ({"type": "line", "repeatable": True, "default": "not-an-array"}, "line"),
    ],
)
def test_a_default_its_own_field_would_refuse_is_rejected(
    gate_home: Path, input_field: dict[str, Any], expected_fragment: str
) -> None:
    spec = _single_option_spec(
        request_id="bad-default",
        option=_proceed_option(
            inputs=[{"id": "value", "label": "Value", **input_field}]
        ),
    )

    with pytest.raises(GateError) as excinfo:
        create_gate(spec)

    assert excinfo.value.code == "invalid_input_field"
    assert excinfo.value.target == "options[0].inputs[0].default"
    assert expected_fragment in str(excinfo.value)


# -- bounds at creation ------------------------------------------------------


def test_a_schema_wider_than_the_submission_bound_is_rejected_at_creation(
    gate_home: Path,
) -> None:
    spec = _single_option_spec(
        request_id="too-wide",
        option=_proceed_option(
            input_schema={
                "type": "object",
                "properties": {
                    f"field_{index}": {"type": "string"}
                    for index in range(MAX_OBJECT_PROPERTIES + 1)
                },
            }
        ),
    )

    with pytest.raises(GateError) as excinfo:
        create_gate(spec)

    assert excinfo.value.code == "schema_too_large"


def test_a_schema_deeper_than_the_submission_bound_is_rejected_at_creation(
    gate_home: Path,
) -> None:
    schema: dict[str, Any] = {"type": "string"}
    for _ in range(12):
        schema = {"type": "object", "properties": {"nested": schema}}
    spec = _single_option_spec(
        request_id="too-deep", option=_proceed_option(input_schema=schema)
    )

    with pytest.raises(GateError) as excinfo:
        create_gate(spec)

    assert excinfo.value.code == "schema_too_large"
