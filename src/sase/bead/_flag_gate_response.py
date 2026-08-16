"""Translation of a persisted FlagTriage response into trusted host input.

Nothing downstream may trust the answering client, so the bead identity and
the flag's *current* thresholds a host effect acts on are read back out of the
persisted request rather than taken from the response.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any, cast

from sase.bead._flag_gate_spec import (
    FLAG_TRIAGE_CLOSE_OPTION_ID,
    FLAG_TRIAGE_EXTEND_OPTION_ID,
    FLAG_TRIAGE_KEEP_OPTION_ID,
    FLAG_TRIAGE_KIND,
    FLAG_TRIAGE_OPTION_IDS,
    FLAG_TRIAGE_REMOVE_OPTION_ID,
    FlagTriageAction,
)
from sase.notification_gates.models import GateError

_FEEDBACK_REQUIRED_ACTIONS = (
    FLAG_TRIAGE_EXTEND_OPTION_ID,
    FLAG_TRIAGE_KEEP_OPTION_ID,
    FLAG_TRIAGE_CLOSE_OPTION_ID,
)


@dataclass(frozen=True)
class FlagTriageResponse:
    """Trusted flag-bead identity and decision translated from a persisted gate."""

    bead_id: str
    project: str
    title: str
    key: str
    old_remove_by_date: str
    old_remove_by_release: str
    action: FlagTriageAction
    feedback: str | None
    source: str
    winner: str | None = None
    remove_by_date: str | None = None
    remove_by_release: str | None = None


def translate_flag_triage_response(
    bundle_path: Path,
    response: Mapping[str, Any],
) -> FlagTriageResponse:
    """Translate one persisted FlagTriage response into trusted host input."""
    from sase.notification_gates.durability import read_json_object

    envelope = read_json_object(bundle_path / "request.json")
    if envelope.get("kind") != FLAG_TRIAGE_KIND:
        raise GateError(
            "invalid_response",
            str(bundle_path / "request.json"),
            "request is not a flag triage gate",
        )
    payload = envelope.get("payload")
    if not isinstance(payload, Mapping):
        raise GateError(
            "invalid_response",
            "payload",
            "flag triage request payload is missing",
        )
    bead_id, project, title = _flag_identity_from_payload(payload)
    key, old_remove_by_date, old_remove_by_release = _flag_thresholds_from_payload(
        payload
    )

    raw_selected = response.get("selected_option_ids")
    if (
        not isinstance(raw_selected, list)
        or len(raw_selected) != 1
        or raw_selected[0] not in FLAG_TRIAGE_OPTION_IDS
    ):
        raise GateError(
            "invalid_response",
            str(bundle_path / "response.json"),
            "flag triage response must select exactly remove, extend, keep, or close",
        )
    action = cast(FlagTriageAction, raw_selected[0])
    option_results = response.get("option_results")
    if not isinstance(option_results, list):
        raise GateError(
            "invalid_response",
            str(bundle_path / "response.json"),
            "flag triage response has no option results",
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
            "flag triage response result does not match its selected action",
        )

    raw_feedback = response.get("feedback")
    feedback = (
        raw_feedback.strip()
        if isinstance(raw_feedback, str) and raw_feedback.strip()
        else None
    )
    if action in _FEEDBACK_REQUIRED_ACTIONS and feedback is None:
        raise GateError(
            "invalid_response",
            "feedback",
            f"{action}ing a flag triage gate requires a reason",
        )

    winner: str | None = None
    remove_by_date: str | None = None
    remove_by_release: str | None = None
    if action == FLAG_TRIAGE_REMOVE_OPTION_ID:
        raw_winner = result.get("winner")
        if raw_winner not in ("enabled", "disabled"):
            raise GateError(
                "invalid_response",
                str(bundle_path / "response.json"),
                "removing a flag triage gate requires a winning branch",
            )
        winner = raw_winner
    elif action == FLAG_TRIAGE_EXTEND_OPTION_ID:
        raw_date = result.get("remove_by_date")
        raw_release = result.get("remove_by_release")
        if (
            not isinstance(raw_date, str)
            or not raw_date
            or not isinstance(raw_release, str)
            or not raw_release
        ):
            raise GateError(
                "invalid_response",
                str(bundle_path / "response.json"),
                "extending a flag triage gate requires new thresholds",
            )
        remove_by_date = raw_date
        remove_by_release = raw_release

    source = response.get("source")
    return FlagTriageResponse(
        bead_id=bead_id,
        project=project,
        title=title,
        key=key,
        old_remove_by_date=old_remove_by_date,
        old_remove_by_release=old_remove_by_release,
        action=action,
        feedback=feedback,
        source=source if isinstance(source, str) and source else "host",
        winner=winner,
        remove_by_date=remove_by_date,
        remove_by_release=remove_by_release,
    )


def _flag_identity_from_payload(
    payload: Mapping[str, Any],
) -> tuple[str, str, str]:
    values: list[str] = []
    for field in ("bead_id", "project", "title"):
        value = payload.get(field)
        if not isinstance(value, str) or not value.strip():
            raise GateError(
                "invalid_flag_payload",
                f"payload.{field}",
                f"flag triage payload requires {field}",
            )
        values.append(value)
    return values[0], values[1], values[2]


def _flag_thresholds_from_payload(
    payload: Mapping[str, Any],
) -> tuple[str, str, str]:
    flag = payload.get("flag")
    if not isinstance(flag, Mapping):
        raise GateError(
            "invalid_flag_payload",
            "payload.flag",
            "flag triage payload requires a flag record",
        )
    values: list[str] = []
    for field in ("key", "remove_by_date", "remove_by_release"):
        value = flag.get(field)
        if not isinstance(value, str) or not value.strip():
            raise GateError(
                "invalid_flag_payload",
                f"payload.flag.{field}",
                f"flag triage payload requires flag.{field}",
            )
        values.append(value)
    return values[0], values[1], values[2]
