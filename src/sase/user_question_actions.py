"""Compatibility facade for shared UserQuestion gate actions."""

from __future__ import annotations

from sase._user_question_actions_models import (
    LIVE_AUTO_POLICY,
    QUESTION_COMMAND_PATH,
    QUESTION_CONTINUATION_MODE,
    QUESTION_OPTION_ID,
    QUESTION_REQUEST_FILE,
    QUESTION_RESPONSE_FILE,
    UserQuestionActionContext,
    UserQuestionActionError,
)
from sase._user_question_actions_payload import (
    automatic_question_response,
    execute_user_question_gate_command,
    question_gate_command_script,
    question_response_schema,
    user_question_gate_spec,
    validate_user_questions,
)
from sase._user_question_actions_response import (
    execute_user_question_response,
    normalize_user_question_response,
    read_user_question_request,
    resolve_user_question_request,
    run_user_question_response_side_effects,
)

__all__ = [
    "QUESTION_COMMAND_PATH",
    "QUESTION_CONTINUATION_MODE",
    "QUESTION_OPTION_ID",
    "QUESTION_REQUEST_FILE",
    "QUESTION_RESPONSE_FILE",
    "UserQuestionActionContext",
    "UserQuestionActionError",
    "automatic_question_response",
    "execute_user_question_gate_command",
    "execute_user_question_response",
    "normalize_user_question_response",
    "question_gate_command_script",
    "question_response_schema",
    "read_user_question_request",
    "resolve_user_question_request",
    "run_user_question_response_side_effects",
    "user_question_gate_spec",
    "validate_user_questions",
]
