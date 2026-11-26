"""Shared types and constants for UserQuestion actions."""

from __future__ import annotations

from dataclasses import dataclass

QUESTION_COMMAND_PATH = "commands/submit"
QUESTION_OPTION_ID = "submit"
QUESTION_CONTINUATION_MODE = "agent_question"
QUESTION_REQUEST_FILE = "question_request.json"
QUESTION_RESPONSE_FILE = "question_response.json"
LIVE_AUTO_POLICY = object()


@dataclass(frozen=True)
class UserQuestionActionContext:
    """Host-owned identifiers and paths for one UserQuestion notification."""

    notification_id: str | None
    host_action_data: dict[str, str]


class UserQuestionActionError(RuntimeError):
    """Deterministic host-side user-question action failure."""

    def __init__(self, code: str, target: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.target = target
