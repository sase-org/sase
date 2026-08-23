"""Shared types for launch approval request handling."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

from sase.agent.launch_types import AgentLaunchResult
from sase.core.agent_launch_wire import (
    LaunchAdmissionSummaryWire,
    LaunchUnitResultWire,
)

LAUNCH_REQUEST_SCHEMA_VERSION = 1
DIRECT_TYPED_LAUNCH_KIND = "direct_typed_launch"


@dataclass(frozen=True)
class LaunchRequestCreationResult:
    request_id: str
    notification_id: str
    response_dir: Path
    request_path: Path
    preview_path: Path
    response_path: Path
    request: dict[str, Any]


LaunchRequestStatus = Literal[
    "approved",
    "rejected",
    "feedback",
    "dispatch_failed",
    "cancelled",
    "timed_out",
]


@dataclass(frozen=True)
class LaunchRequestOutcome:
    """Deterministic terminal result observed by an agent-side requester."""

    status: LaunchRequestStatus
    request_id: str
    notification_id: str
    selected_option_ids: tuple[str, ...]
    message: str
    response: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "request_id": self.request_id,
            "notification_id": self.notification_id,
            "selected_option_ids": list(self.selected_option_ids),
            "message": self.message,
            "response": self.response,
        }


@dataclass(frozen=True)
class ApprovedLaunchDispatchResult:
    request_id: str
    results: list[AgentLaunchResult]
    summary: LaunchAdmissionSummaryWire | None = None
    unit_results: tuple[LaunchUnitResultWire, ...] = ()
    plan_digest: str | None = None
    admission_complete: bool = True

    @property
    def launched_count(self) -> int:
        if self.summary is not None:
            return int(self.summary.launched)
        return len(self.results)


class LaunchRequestError(RuntimeError):
    """Deterministic launch-request validation or dispatch failure."""

    def __init__(self, code: str, target: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.target = target


class TypedAdmissionRequiredError(RuntimeError):
    """Enabled ``%if`` / ``%proc`` reached the agent-only launch path."""
