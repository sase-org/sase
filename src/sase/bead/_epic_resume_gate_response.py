"""Translation of a persisted EpicResume response into trusted host input.

Nothing downstream may trust the answering client, so the epic a host effect
acts on is read back out of the persisted request payload rather than taken
from the response.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from sase.bead._epic_resume_gate_spec import (
    EPIC_RESUME_KIND,
    EPIC_RESUME_RESUME_OPTION_ID,
    EpicResumeAction,
)
from sase.notification_gates.kind_validation.epic_resume_payload import (
    parse_epic_resume_payload,
)
from sase.notification_gates.models import GateError


@dataclass(frozen=True)
class EpicResumeResponse:
    """Trusted epic identity and decision translated from a persisted gate."""

    project: str
    epic_id: str
    action: EpicResumeAction
    feedback: str | None
    source: str


def translate_epic_resume_response(
    bundle_path: Path,
    response: Mapping[str, Any],
) -> EpicResumeResponse:
    """Translate one persisted EpicResume response into trusted host input."""
    from sase.notification_gates.durability import read_json_object

    envelope = read_json_object(bundle_path / "request.json")
    if envelope.get("kind") != EPIC_RESUME_KIND:
        raise GateError(
            "invalid_response",
            str(bundle_path / "request.json"),
            "request is not an epic resume gate",
        )
    payload = envelope.get("payload")
    if not isinstance(payload, Mapping):
        raise GateError(
            "invalid_response",
            "payload",
            "epic resume request payload is missing",
        )
    parsed = parse_epic_resume_payload(payload)

    raw_selected = response.get("selected_option_ids")
    if (
        not isinstance(raw_selected, list)
        or len(raw_selected) != 1
        or raw_selected[0] != EPIC_RESUME_RESUME_OPTION_ID
    ):
        raise GateError(
            "invalid_response",
            str(bundle_path / "response.json"),
            "epic resume response must select exactly resume",
        )
    option_results = response.get("option_results")
    if not isinstance(option_results, list):
        raise GateError(
            "invalid_response",
            str(bundle_path / "response.json"),
            "epic resume response has no option results",
        )
    result = next(
        (
            entry.get("result")
            for entry in option_results
            if isinstance(entry, Mapping)
            and entry.get("id") == EPIC_RESUME_RESUME_OPTION_ID
        ),
        None,
    )
    if (
        not isinstance(result, Mapping)
        or result.get("action") != EPIC_RESUME_RESUME_OPTION_ID
    ):
        raise GateError(
            "invalid_response",
            str(bundle_path / "response.json"),
            "epic resume response result does not match its selected action",
        )

    raw_feedback = response.get("feedback")
    feedback = (
        raw_feedback.strip()
        if isinstance(raw_feedback, str) and raw_feedback.strip()
        else None
    )
    source = response.get("source")
    return EpicResumeResponse(
        project=parsed.project,
        epic_id=parsed.epic_id,
        action=EPIC_RESUME_RESUME_OPTION_ID,
        feedback=feedback,
        source=source if isinstance(source, str) and source else "host",
    )
