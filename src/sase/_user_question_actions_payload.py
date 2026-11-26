"""UserQuestion gate request construction and response validation."""

from __future__ import annotations

import json
import sys
import time
from collections.abc import Mapping
from typing import Any

from sase._user_question_actions_models import (
    LIVE_AUTO_POLICY,
    QUESTION_COMMAND_PATH,
    QUESTION_CONTINUATION_MODE,
    QUESTION_OPTION_ID,
    QUESTION_REQUEST_FILE,
    QUESTION_RESPONSE_FILE,
    UserQuestionActionError,
)
from sase.notification_gates.entrypoints import (
    gate_command_entrypoint,
    python_gate_command_script,
)


def user_question_gate_spec(
    questions: list[dict[str, Any]],
    *,
    session_id: str,
    producer: Mapping[str, Any] | None = None,
    action_data: Mapping[str, str] | None = None,
    auto: bool = False,
    auto_policy_snapshot: Mapping[str, Any] | None | object = LIVE_AUTO_POLICY,
    request_timestamp: float | None = None,
) -> dict[str, Any]:
    """Build the shared v3 UserQuestion gate request body.

    The single source of truth for the question gate turn's request.
    """
    normalized_questions = validate_user_questions(questions)
    from sase.core.question_copy_facade import (
        QuestionCopyValidationError,
        normalize_questions_copy,
    )

    try:
        normalized_questions = normalize_questions_copy(normalized_questions)
    except QuestionCopyValidationError as exc:
        target = exc.target.replace("question[", "payload.questions[", 1)
        raise UserQuestionActionError(
            "invalid_question_copy", target, exc.message
        ) from exc
    response_schema = question_response_schema(normalized_questions)
    summary = "; ".join(
        str(question.get("question") or "?") for question in normalized_questions[:3]
    )
    # Attach the creator's live record snapshot: the gate service
    # evaluates exactly once from it. ``enabled`` means a non-manual
    # profile; without a live record the service falls back to the legacy
    # bare-``%auto`` translation. A manual snapshot rides along disabled
    # so the parked gate carries its deciding revision (rule ``manual``),
    # exactly like a manual plan gate.
    if auto_policy_snapshot is LIVE_AUTO_POLICY:
        try:
            import os as _os

            from sase.autonomy.record import live_record as _live_record

            _record = _live_record(_os.environ.get("SASE_ARTIFACTS_DIR") or "")
        except Exception:
            _record = None
    else:
        _record = (
            dict(auto_policy_snapshot)
            if isinstance(auto_policy_snapshot, Mapping)
            else None
        )
    auto_block: dict[str, Any] | bool = auto
    if _record is not None and _record.get("profile") == "manual":
        auto_block = {
            "enabled": False,
            "argument": None,
            "policy": _record,
        }
    elif auto:
        if _record is not None:
            auto_block = {
                "enabled": True,
                "argument": _record.get("selection") or None,
                "policy": _record,
            }
        else:
            auto_block = {"enabled": True, "argument": None}
    return {
        "schema_version": 3,
        "kind": "question",
        "request_id": session_id,
        "producer": dict(producer or {}),
        "continuation_mode": QUESTION_CONTINUATION_MODE,
        "payload": {
            "questions": normalized_questions,
            "session_id": session_id,
            "timestamp": (
                request_timestamp if request_timestamp is not None else time.time()
            ),
        },
        "presentation": {
            "notes": [summary] if summary else ["Agent is asking a question"],
            "tags": ["question"],
            "action_data": dict(action_data or {}),
        },
        "query": QUESTION_OPTION_ID,
        "primary_branch": [QUESTION_OPTION_ID],
        "options": [
            {
                "id": QUESTION_OPTION_ID,
                "label": "Submit answers",
                "icon": "✅",
                "command": {"argv": [QUESTION_COMMAND_PATH]},
                "input_schema": response_schema,
                "result_schema": response_schema,
                "feedback": "optional",
            }
        ],
        "resources": [
            {
                "path": QUESTION_COMMAND_PATH,
                "role": "command",
                "content": question_gate_command_script(),
            }
        ],
        "auto": auto_block,
    }


def validate_user_questions(value: object) -> list[dict[str, Any]]:
    """Validate and return the adapter-owned question list."""
    if not isinstance(value, list) or not value:
        raise UserQuestionActionError(
            "invalid_question_payload", "payload.questions", "questions are required"
        )
    normalized: list[dict[str, Any]] = []
    for index, raw_question in enumerate(value):
        target = f"payload.questions[{index}]"
        if not isinstance(raw_question, Mapping):
            raise UserQuestionActionError(
                "invalid_question_payload", target, "question must be an object"
            )
        question = dict(raw_question)
        prompt = question.get("question")
        if not isinstance(prompt, str) or not prompt.strip():
            raise UserQuestionActionError(
                "invalid_question_payload",
                f"{target}.question",
                "question text is required",
            )
        options = question.get("options", [])
        if not isinstance(options, list):
            raise UserQuestionActionError(
                "invalid_question_payload",
                f"{target}.options",
                "question options must be an array",
            )
        labels: set[str] = set()
        for option_index, raw_option in enumerate(options):
            option_target = f"{target}.options[{option_index}]"
            if not isinstance(raw_option, Mapping):
                raise UserQuestionActionError(
                    "invalid_question_payload",
                    option_target,
                    "question option must be an object",
                )
            label = raw_option.get("label")
            if not isinstance(label, str) or not label.strip():
                raise UserQuestionActionError(
                    "invalid_question_payload",
                    f"{option_target}.label",
                    "question option label is required",
                )
            if label in labels or label == "Other":
                raise UserQuestionActionError(
                    "invalid_question_payload",
                    f"{option_target}.label",
                    "question option labels must be unique and cannot be 'Other'",
                )
            labels.add(label)
        if not isinstance(question.get("multiSelect", False), bool):
            raise UserQuestionActionError(
                "invalid_question_payload",
                f"{target}.multiSelect",
                "multiSelect must be a boolean",
            )
        normalized.append(question)
    return normalized


def question_response_schema(questions: list[dict[str, Any]]) -> dict[str, Any]:
    """Build the complete normalized-answer schema for *questions*."""
    answer_schemas: list[dict[str, Any]] = []
    for question in questions:
        options = question.get("options", [])
        labels = [
            str(option["label"])
            for option in options
            if isinstance(option, Mapping) and isinstance(option.get("label"), str)
        ]
        selectable = [*labels, "Other"]
        selected_schema: dict[str, Any] = {
            "type": "array",
            "items": {"enum": selectable},
            "uniqueItems": True,
            "maxItems": len(selectable) if question.get("multiSelect", False) else 1,
        }
        answer_schemas.append(
            {
                "type": "object",
                "required": ["question", "selected", "custom_feedback"],
                "properties": {
                    "question": {"const": question["question"]},
                    "selected": selected_schema,
                    "custom_feedback": {
                        "type": ["string", "null"],
                    },
                },
                "allOf": [
                    {
                        "anyOf": [
                            {"properties": {"selected": {"minItems": 1}}},
                            {
                                "properties": {
                                    "custom_feedback": {
                                        "type": "string",
                                        "minLength": 1,
                                    }
                                }
                            },
                        ]
                    },
                    {
                        "if": {
                            "properties": {
                                "selected": {"contains": {"const": "Other"}}
                            },
                            "required": ["selected"],
                        },
                        "then": {
                            "properties": {
                                "custom_feedback": {
                                    "type": "string",
                                    "minLength": 1,
                                }
                            }
                        },
                    },
                ],
                "additionalProperties": False,
            }
        )
    return {
        "type": "object",
        "required": ["answers", "global_note"],
        "properties": {
            "answers": {
                "type": "array",
                "prefixItems": answer_schemas,
                "items": False,
                "minItems": len(answer_schemas),
                "maxItems": len(answer_schemas),
            },
            "global_note": {"type": "string"},
        },
        "additionalProperties": False,
    }


def normalize_user_question_response_data(
    questions: list[dict[str, Any]], value: Mapping[str, Any]
) -> dict[str, Any]:
    """Return a stable answer object after validating form completeness."""
    if not isinstance(value, Mapping):
        raise UserQuestionActionError(
            "invalid_question_input", "input", "question input must be an object"
        )
    raw_answers = value.get("answers")
    if not isinstance(raw_answers, list):
        raw_answers = raw_answers  # Let JSON Schema provide the precise failure.
        answers: object = raw_answers
    else:
        answers = [
            {
                "question": answer.get("question"),
                "selected": answer.get("selected", []),
                "custom_feedback": answer.get("custom_feedback"),
            }
            if isinstance(answer, Mapping)
            else answer
            for answer in raw_answers
        ]
    global_note = value.get("global_note", "")
    normalized = {
        "answers": answers,
        "global_note": "" if global_note is None else global_note,
    }
    try:
        from jsonschema import Draft202012Validator  # type: ignore[import-untyped]

        Draft202012Validator(question_response_schema(questions)).validate(normalized)
    except Exception as exc:
        raise UserQuestionActionError(
            "incomplete_question_form", "input", str(exc)
        ) from exc
    return normalized


def automatic_question_response(payload: Mapping[str, Any]) -> dict[str, Any]:
    """Build the first-option response used by question auto-resolution."""
    questions = validate_user_questions(payload.get("questions"))
    answers = []
    for question in questions:
        options = question.get("options", [])
        selected = [str(options[0]["label"])] if options else []
        answers.append(
            {
                "question": question["question"],
                "selected": selected,
                "custom_feedback": None,
            }
        )
    return normalize_user_question_response_data(
        questions, {"answers": answers, "global_note": ""}
    )


@gate_command_entrypoint
def execute_user_question_gate_command() -> int:
    """Entry point used only by the adapter-approved question command script."""
    try:
        value = json.load(sys.stdin)
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        print(f"invalid question input: {exc}", file=sys.stderr)
        return 2
    if not isinstance(value, dict):
        print("question input must be an object", file=sys.stderr)
        return 2
    print(json.dumps(value, sort_keys=True))
    return 0


def question_gate_command_script() -> str:
    """Return the only command wrapper accepted by the question adapter."""
    return python_gate_command_script(
        "from sase.user_question_actions import execute_user_question_gate_command\n"
        "raise SystemExit(execute_user_question_gate_command())\n"
    )
