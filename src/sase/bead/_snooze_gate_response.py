"""Translation of a persisted BeadSnooze response into trusted host input.

Nothing downstream may trust the answering client, so the bead a host effect
acts on and the snooze record it reasons about are read back out of the
persisted request rather than taken from the response. Only the decision --
the selected action, its validated result, and the reviewer's note -- comes
from the answer.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any, cast

from sase.bead._snooze_gate_spec import (
    BEAD_SNOOZE_KIND,
    BEAD_SNOOZE_OPTION_IDS,
    BEAD_SNOOZE_SNOOZE_OPTION_ID,
    BeadSnoozeAction,
)
from sase.bead.model import SnoozeRecord
from sase.notification_gates.models import GateError


@dataclass(frozen=True)
class BeadSnoozeResponse:
    """Trusted task identity and decision translated from a persisted gate."""

    bead_id: str
    project: str
    title: str
    action: BeadSnoozeAction
    feedback: str | None
    source: str
    snooze: SnoozeRecord
    duration: str | None = None


def translate_bead_snooze_response(
    bundle_path: Path,
    response: Mapping[str, Any],
) -> BeadSnoozeResponse:
    """Translate one persisted BeadSnooze response into trusted host input."""
    from sase.notification_gates.durability import read_json_object

    envelope = read_json_object(bundle_path / "request.json")
    if envelope.get("kind") != BEAD_SNOOZE_KIND:
        raise GateError(
            "invalid_response",
            str(bundle_path / "request.json"),
            "request is not a bead snooze gate",
        )
    payload = envelope.get("payload")
    if not isinstance(payload, Mapping):
        raise GateError(
            "invalid_response",
            "payload",
            "bead snooze request payload is missing",
        )
    bead_id, project, title = _task_identity_from_payload(payload)
    snooze = _snooze_from_payload(payload)

    raw_selected = response.get("selected_option_ids")
    if (
        not isinstance(raw_selected, list)
        or len(raw_selected) != 1
        or raw_selected[0] not in BEAD_SNOOZE_OPTION_IDS
    ):
        raise GateError(
            "invalid_response",
            str(bundle_path / "response.json"),
            "bead snooze response must select exactly close, ready, or snooze",
        )
    action = cast(BeadSnoozeAction, raw_selected[0])
    option_results = response.get("option_results")
    if not isinstance(option_results, list):
        raise GateError(
            "invalid_response",
            str(bundle_path / "response.json"),
            "bead snooze response has no option results",
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
            "bead snooze response result does not match its selected action",
        )

    raw_feedback = response.get("feedback")
    feedback = (
        raw_feedback.strip()
        if isinstance(raw_feedback, str) and raw_feedback.strip()
        else None
    )
    duration = result.get("duration")
    if action == BEAD_SNOOZE_SNOOZE_OPTION_ID and not isinstance(duration, str):
        raise GateError(
            "invalid_response",
            str(bundle_path / "response.json"),
            "re-snoozing a bead snooze gate requires a new wake time",
        )
    source = response.get("source")
    return BeadSnoozeResponse(
        bead_id=bead_id,
        project=project,
        title=title,
        action=action,
        feedback=feedback,
        source=source if isinstance(source, str) and source else "host",
        snooze=snooze,
        duration=duration if isinstance(duration, str) else None,
    )


def _snooze_from_payload(payload: Mapping[str, Any]) -> SnoozeRecord:
    from sase.bead.snooze_codec import snooze_from_dict

    record = snooze_from_dict(payload.get("snooze"))
    if record is None:
        raise GateError(
            "invalid_task_payload",
            "payload.snooze",
            "bead snooze payload requires a snooze record",
        )
    return record


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
                f"bead snooze payload requires {field}",
            )
        values.append(value)
    return values[0], values[1], values[2]
