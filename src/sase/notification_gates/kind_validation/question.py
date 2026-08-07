"""Validation contract for UserQuestion gates."""

from __future__ import annotations

from typing import Any

from sase.notification_gates.kind_validation.resources import read_gate_resource
from sase.notification_gates.models import (
    GateError,
    GateSpec,
    stamp_schema_dialect,
)


def validate_question_spec(spec: GateSpec) -> None:
    """Keep UserQuestion gates on the registered complete-form contract."""
    from sase.user_question_actions import (
        QUESTION_COMMAND_PATH,
        QUESTION_CONTINUATION_MODE,
        UserQuestionActionError,
        question_gate_command_script,
        question_response_schema,
        validate_user_questions,
    )

    if spec.continuation_mode != QUESTION_CONTINUATION_MODE:
        raise GateError(
            "invalid_question_continuation",
            "continuation_mode",
            f"question gates require {QUESTION_CONTINUATION_MODE}",
        )
    try:
        questions = validate_user_questions(spec.payload.get("questions"))
    except UserQuestionActionError as exc:
        raise GateError(exc.code, exc.target, str(exc)) from exc
    _validate_question_payload(spec)
    _validate_question_options(spec, question_response_schema(questions))

    resources = {resource.path: resource for resource in spec.resources}
    if set(resources) != {QUESTION_COMMAND_PATH}:
        raise GateError(
            "invalid_question_resources",
            "resources",
            "question gates require only the registered submit command",
        )
    content = read_gate_resource(
        resources[QUESTION_COMMAND_PATH],
        code="invalid_question_command",
        description="question command",
    )
    if content != question_gate_command_script():
        raise GateError(
            "invalid_question_command",
            QUESTION_COMMAND_PATH,
            "question command does not match the registered adapter",
        )


def _validate_question_payload(spec: GateSpec) -> None:
    session_id = spec.payload.get("session_id")
    if not isinstance(session_id, str) or not session_id:
        raise GateError(
            "invalid_question_payload",
            "payload.session_id",
            "question session id is required",
        )
    if spec.request_id is not None and session_id != spec.request_id:
        raise GateError(
            "invalid_question_payload",
            "payload.session_id",
            "question session id must match request id",
        )


def _validate_question_options(spec: GateSpec, expected_schema: dict[str, Any]) -> None:
    from sase.user_question_actions import QUESTION_COMMAND_PATH, QUESTION_OPTION_ID

    if (
        spec.query != QUESTION_OPTION_ID
        or len(spec.options) != 1
        or spec.branches != ((QUESTION_OPTION_ID,),)
    ):
        raise GateError(
            "invalid_question_options",
            "options",
            "question gates require one singleton submit branch",
        )
    option = spec.options[0]
    if option.id != QUESTION_OPTION_ID or option.command.argv != (
        QUESTION_COMMAND_PATH,
    ):
        raise GateError(
            "invalid_question_options",
            "options",
            "question gates require the registered submit option",
        )
    stamped_schema = stamp_schema_dialect(expected_schema)
    if option.input_schema != stamped_schema or option.result_schema != stamped_schema:
        raise GateError(
            "invalid_question_schema",
            "options.submit",
            "question submit schemas must match the adapter input form",
        )
