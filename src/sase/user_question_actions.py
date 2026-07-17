"""Shared UserQuestion gate creation, response execution, and compatibility."""

from __future__ import annotations

import json
import sys
import time
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from sase.notification_gates.entrypoints import gate_command_entrypoint

QUESTION_COMMAND_PATH = "commands/submit"
QUESTION_CHOICE_ID = "submit"
QUESTION_CONTINUATION_MODE = "agent_question"
QUESTION_REQUEST_FILE = "question_request.json"
QUESTION_RESPONSE_FILE = "question_response.json"


@dataclass(frozen=True)
class UserQuestionActionContext:
    """Host-owned identifiers and paths for one UserQuestion notification."""

    notification_id: str | None
    host_action_data: dict[str, str]


@dataclass(frozen=True)
class _UserQuestionActionResult:
    """Result returned after a question response reaches durable storage."""

    notification_id: str | None
    response_file: str
    response_path: Path
    response_json: dict[str, Any]
    answers: dict[str, Any]
    message: str = "Question answered"


class UserQuestionActionError(RuntimeError):
    """Deterministic host-side user-question action failure."""

    def __init__(self, code: str, target: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.target = target


def create_user_question_gate(
    questions: list[dict[str, Any]],
    *,
    session_id: str,
    producer: Mapping[str, Any] | None = None,
    action_data: Mapping[str, str] | None = None,
    auto: bool = False,
) -> Any:
    """Create a neutral UserQuestion gate for the current agent continuation."""
    normalized_questions = validate_user_questions(questions)
    response_schema = question_response_schema(normalized_questions)
    summary = "; ".join(
        str(question.get("question") or "?") for question in normalized_questions[:3]
    )

    from sase.notification_gates.service import create_gate

    return create_gate(
        {
            "schema_version": 1,
            "kind": "question",
            "request_id": session_id,
            "producer": dict(producer or {}),
            "continuation_mode": QUESTION_CONTINUATION_MODE,
            "payload": {
                "questions": normalized_questions,
                "session_id": session_id,
                "timestamp": time.time(),
            },
            "presentation": {
                "notes": [summary] if summary else ["Agent is asking a question"],
                "tags": ["question"],
                "action_data": dict(action_data or {}),
            },
            "choices": [
                {
                    "id": QUESTION_CHOICE_ID,
                    "label": "Submit answers",
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
            "auto": auto,
        }
    )


def execute_user_question_response(
    context: UserQuestionActionContext,
    response_data: Mapping[str, Any],
    *,
    source: str = "question_response",
) -> _UserQuestionActionResult:
    """Resolve a neutral UserQuestion, with legacy in-flight fallback."""
    bundle = _resolve_question_bundle(context)
    questions = _questions_from_request_root(bundle.root, legacy=bundle.legacy)
    normalized = _normalize_user_question_response(questions, response_data)

    if bundle.legacy:
        response_path = bundle.response
        _write_json_once(response_path, normalized, context.notification_id)
        response_json = normalized
        response_file = QUESTION_RESPONSE_FILE
    else:
        from sase.notification_gates.executor import execute_gate_choice
        from sase.notification_gates.models import GateError
        from sase.notification_gates.paths import RESPONSE_FILENAME

        try:
            shared_feedback = response_data.get("feedback")
            if not isinstance(shared_feedback, str):
                shared_feedback = normalized.get("global_note")
            if not isinstance(shared_feedback, str) or not shared_feedback.strip():
                shared_feedback = None
            execution = execute_gate_choice(
                bundle.root,
                QUESTION_CHOICE_ID,
                normalized,
                feedback=shared_feedback,
                source=source,
            )
        except GateError as exc:
            code = (
                "conflict_already_handled"
                if exc.code in {"already_answered", "gate_cancelled"}
                else exc.code
            )
            raise UserQuestionActionError(code, exc.target, str(exc)) from exc
        if execution.already_completed:
            raise UserQuestionActionError(
                "conflict_already_handled",
                context.notification_id or str(bundle.root),
                "response already exists",
            )
        response_json = execution.response
        result = response_json.get("result")
        if not isinstance(result, dict):
            raise UserQuestionActionError(
                "invalid_response",
                str(bundle.response),
                "question command returned no result object",
            )
        normalized = _normalize_user_question_response(questions, result)
        response_path = bundle.response
        response_file = RESPONSE_FILENAME

    _run_question_side_effects(context, source=source)
    return _UserQuestionActionResult(
        notification_id=context.notification_id,
        response_file=response_file,
        response_path=response_path,
        response_json=response_json,
        answers=normalized,
    )


def read_user_question_request(response_dir: str | Path) -> dict[str, Any]:
    """Read a neutral question payload first, then an in-flight legacy request."""
    root = Path(response_dir).expanduser()
    return _request_from_root(root, legacy=not (root / "request.json").is_file())


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


def _normalize_user_question_response(
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
    return _normalize_user_question_response(
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
    return (
        f"#!{sys.executable}\n"
        "from sase.user_question_actions import execute_user_question_gate_command\n"
        "raise SystemExit(execute_user_question_gate_command())\n"
    )


def _resolve_question_bundle(context: UserQuestionActionContext) -> Any:
    from sase.notification_gates.models import GateError
    from sase.notification_gates.paths import (
        CANCELLATION_FILENAME,
        REQUEST_FILENAME,
        RESPONSE_FILENAME,
        ResolvedGateBundle,
        assert_owned_bundle,
        resolve_action_bundle,
    )

    bundle = resolve_action_bundle("UserQuestion", context.host_action_data)
    if bundle is not None and (bundle.request.is_file() or bundle.response.is_file()):
        return bundle
    raw_root = context.host_action_data.get("response_dir")
    if not raw_root:
        raise UserQuestionActionError(
            "invalid_request", "response_dir", "response_dir is missing"
        )
    root = Path(raw_root).expanduser()
    neutral_request = root / REQUEST_FILENAME
    if neutral_request.is_file():
        try:
            root = assert_owned_bundle(root)
        except GateError as exc:
            raise UserQuestionActionError(exc.code, exc.target, str(exc)) from exc
        return ResolvedGateBundle(
            kind="question",
            root=root,
            request=root / REQUEST_FILENAME,
            response=root / RESPONSE_FILENAME,
            cancellation=root / CANCELLATION_FILENAME,
            legacy=False,
        )
    return ResolvedGateBundle(
        kind="question",
        root=root,
        request=root / QUESTION_REQUEST_FILE,
        response=root / QUESTION_RESPONSE_FILE,
        cancellation=root / CANCELLATION_FILENAME,
        legacy=True,
    )


def _questions_from_request_root(root: Path, *, legacy: bool) -> list[dict[str, Any]]:
    data = _request_from_root(root, legacy=legacy)
    return validate_user_questions(data.get("questions"))


def _request_from_root(root: Path, *, legacy: bool) -> dict[str, Any]:
    if not legacy:
        from sase.notification_gates.hashing import load_and_verify_bundle
        from sase.notification_gates.models import GateError

        try:
            envelope, adapter = load_and_verify_bundle(root)
        except GateError as exc:
            raise UserQuestionActionError(exc.code, exc.target, str(exc)) from exc
        if adapter.kind != "question":
            raise UserQuestionActionError(
                "invalid_request", str(root), "gate is not a question request"
            )
        payload = envelope.get("payload")
        if not isinstance(payload, dict):
            raise UserQuestionActionError(
                "invalid_request", str(root / "request.json"), "payload is missing"
            )
        return payload

    request_path = root / QUESTION_REQUEST_FILE
    try:
        value = json.loads(request_path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise UserQuestionActionError(
            "invalid_request", str(request_path), "question request is missing"
        ) from exc
    except (OSError, json.JSONDecodeError) as exc:
        raise UserQuestionActionError(
            "invalid_request", str(request_path), "question request is invalid"
        ) from exc
    if not isinstance(value, dict):
        raise UserQuestionActionError(
            "invalid_request", str(request_path), "question request must be an object"
        )
    return value


def _write_json_once(
    response_path: Path,
    response_json: dict[str, Any],
    notification_id: str | None,
) -> None:
    try:
        with response_path.open("x", encoding="utf-8") as stream:
            json.dump(response_json, stream, indent=2)
            stream.write("\n")
    except FileExistsError as exc:
        raise UserQuestionActionError(
            "conflict_already_handled",
            notification_id or str(response_path),
            "response already exists",
        ) from exc


def _run_question_side_effects(
    context: UserQuestionActionContext, *, source: str
) -> None:
    if not context.notification_id:
        return
    try:
        from sase.notifications import mark_dismissed

        mark_dismissed(context.notification_id)
    except Exception:
        pass
    try:
        from sase.notifications.pending_actions import mark_already_handled

        mark_already_handled(
            context.notification_id,
            source=source,
            action=QUESTION_CHOICE_ID,
        )
    except Exception:
        pass


__all__ = [
    "QUESTION_CHOICE_ID",
    "QUESTION_COMMAND_PATH",
    "QUESTION_CONTINUATION_MODE",
    "QUESTION_REQUEST_FILE",
    "QUESTION_RESPONSE_FILE",
    "UserQuestionActionContext",
    "UserQuestionActionError",
    "automatic_question_response",
    "create_user_question_gate",
    "execute_user_question_gate_command",
    "execute_user_question_response",
    "question_gate_command_script",
    "question_response_schema",
    "read_user_question_request",
    "validate_user_questions",
]
