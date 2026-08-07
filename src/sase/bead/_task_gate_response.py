"""Translation of a persisted TaskTriage response into trusted host input.

Nothing downstream may trust the answering client, so the bead identity a host
effect acts on is read back out of the persisted request rather than taken
from the response.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any, cast

from sase.bead._task_gate_spec import (
    TASK_TRIAGE_CLOSE_OPTION_ID,
    TASK_TRIAGE_KIND,
    TASK_TRIAGE_OPTION_IDS,
    TASK_TRIAGE_SNOOZE_OPTION_ID,
    TaskTriageAction,
)
from sase.notification_gates.models import GateError


@dataclass(frozen=True)
class TaskTriageResponse:
    """Trusted task identity and decision translated from a persisted gate."""

    bead_id: str
    project: str
    title: str
    action: TaskTriageAction
    feedback: str | None
    source: str


def translate_task_triage_response(
    bundle_path: Path,
    response: Mapping[str, Any],
) -> TaskTriageResponse:
    """Translate one persisted TaskTriage response into trusted host input."""
    from sase.notification_gates.durability import read_json_object

    envelope = read_json_object(bundle_path / "request.json")
    if envelope.get("kind") != TASK_TRIAGE_KIND:
        raise GateError(
            "invalid_response",
            str(bundle_path / "request.json"),
            "request is not a task triage gate",
        )
    payload = envelope.get("payload")
    if not isinstance(payload, Mapping):
        raise GateError(
            "invalid_response",
            "payload",
            "task triage request payload is missing",
        )
    bead_id, project, title = _task_identity_from_payload(payload)

    raw_selected = response.get("selected_option_ids")
    if (
        not isinstance(raw_selected, list)
        or len(raw_selected) != 1
        or raw_selected[0] not in TASK_TRIAGE_OPTION_IDS
    ):
        raise GateError(
            "invalid_response",
            str(bundle_path / "response.json"),
            "task triage response must select exactly launch, close, or snooze",
        )
    action = raw_selected[0]
    option_results = response.get("option_results")
    if not isinstance(option_results, list):
        raise GateError(
            "invalid_response",
            str(bundle_path / "response.json"),
            "task triage response has no option results",
        )
    result = next(
        (
            entry.get("result")
            for entry in option_results
            if isinstance(entry, Mapping) and entry.get("id") == action
        ),
        None,
    )
    if not isinstance(result, Mapping) or result.get("action") != action:
        raise GateError(
            "invalid_response",
            str(bundle_path / "response.json"),
            "task triage response result does not match its selected action",
        )

    raw_feedback = response.get("feedback")
    feedback = (
        raw_feedback.strip()
        if isinstance(raw_feedback, str) and raw_feedback.strip()
        else None
    )
    if action == TASK_TRIAGE_CLOSE_OPTION_ID and feedback is None:
        raise GateError(
            "invalid_response",
            "feedback",
            "closing a task triage gate requires a reason",
        )
    if action == TASK_TRIAGE_SNOOZE_OPTION_ID and feedback is None:
        raise GateError(
            "invalid_response",
            "feedback",
            "snoozing a task triage gate requires a wake time",
        )
    source = response.get("source")
    return TaskTriageResponse(
        bead_id=bead_id,
        project=project,
        title=title,
        action=cast(TaskTriageAction, action),
        feedback=feedback,
        source=source if isinstance(source, str) and source else "host",
    )


def validate_task_triage_feedback(
    selected_option_ids: Sequence[str], feedback: str | None
) -> None:
    """Reject an unparsable triage-time snooze before the gate becomes terminal.

    The duration rides in the free-text feedback field, so a typo is the one
    input error the option command cannot catch. Checking it here — before the
    response is persisted — leaves the gate pending, so a mistyped duration
    costs a retry rather than the task's triage gate.
    """
    if TASK_TRIAGE_SNOOZE_OPTION_ID not in selected_option_ids:
        return
    from sase.bead.snooze_time import SnoozeTimeError, parse_snooze_request

    try:
        parse_snooze_request(feedback or "")
    except SnoozeTimeError as exc:
        raise GateError("invalid_snooze_duration", "feedback", str(exc)) from exc


def _task_identity_from_payload(
    payload: Mapping[str, Any],
) -> tuple[str, str, str]:
    values: list[str] = []
    for field in ("bead_id", "project", "title"):
        value = payload.get(field)
        if not isinstance(value, str) or not value.strip():
            raise GateError(
                "invalid_task_payload",
                f"payload.{field}",
                f"task triage payload requires {field}",
            )
        values.append(value)
    return values[0], values[1], values[2]
