"""Structured payload parsing for BeadSnooze gate validation."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, cast

from sase.notification_gates.kind_validation.task_triage_payload import (
    TaskTriagePayload,
    parse_task_bead_payload,
)
from sase.notification_gates.models import GateError

if TYPE_CHECKING:
    from sase.bead.model import SnoozeRecord

BEAD_SNOOZE_PAYLOAD_CODE = "invalid_bead_snooze_payload"
_BEAD_SNOOZE_LABEL = "bead snooze"
_SNOOZE_FIELDS = frozenset(
    {
        "until",
        "snoozed_at",
        "snoozed_by",
        "plus_one_target",
        "plus_one_baseline",
        "reason",
    }
)


@dataclass(frozen=True)
class BeadSnoozePayload:
    """The validated view of a bead snooze gate payload.

    The task fields are the TaskTriage gate's, unchanged: a woken bead is the
    same bead, so its gate presents it with the same contract.
    """

    task: TaskTriagePayload
    snooze: SnoozeRecord


def parse_bead_snooze_payload(payload: Mapping[str, Any]) -> BeadSnoozePayload:
    """Validate *payload* against the structured presentation contract."""
    task = parse_task_bead_payload(
        payload,
        code=BEAD_SNOOZE_PAYLOAD_CODE,
        label=_BEAD_SNOOZE_LABEL,
        extra_fields=frozenset({"snooze"}),
    )
    return BeadSnoozePayload(task=task, snooze=_parse_snooze(payload.get("snooze")))


def _parse_snooze(raw_snooze: object) -> SnoozeRecord:
    from sase.bead.model import SnoozeRecord

    if not isinstance(raw_snooze, Mapping) or set(raw_snooze) != _SNOOZE_FIELDS:
        raise GateError(
            BEAD_SNOOZE_PAYLOAD_CODE,
            "payload.snooze",
            "bead snooze payload snooze record is malformed",
        )
    for field in ("until", "snoozed_at", "snoozed_by", "reason"):
        if not isinstance(raw_snooze.get(field), str):
            raise GateError(
                BEAD_SNOOZE_PAYLOAD_CODE,
                f"payload.snooze.{field}",
                f"bead snooze payload snooze {field} must be a string",
            )
    for field in ("plus_one_target", "plus_one_baseline"):
        value = raw_snooze.get(field)
        if value is not None and (
            not isinstance(value, int) or isinstance(value, bool)
        ):
            raise GateError(
                BEAD_SNOOZE_PAYLOAD_CODE,
                f"payload.snooze.{field}",
                f"bead snooze payload snooze {field} must be null or an integer",
            )
    record = SnoozeRecord(
        until=cast(str, raw_snooze["until"]),
        snoozed_at=cast(str, raw_snooze["snoozed_at"]),
        snoozed_by=cast(str, raw_snooze["snoozed_by"]),
        plus_one_target=cast("int | None", raw_snooze["plus_one_target"]),
        plus_one_baseline=cast("int | None", raw_snooze["plus_one_baseline"]),
        reason=cast(str, raw_snooze["reason"]),
    )
    try:
        record.validate()
    except ValueError as exc:
        raise GateError(
            BEAD_SNOOZE_PAYLOAD_CODE,
            "payload.snooze",
            str(exc),
        ) from exc
    return record


__all__ = [
    "BEAD_SNOOZE_PAYLOAD_CODE",
    "BeadSnoozePayload",
    "parse_bead_snooze_payload",
]
