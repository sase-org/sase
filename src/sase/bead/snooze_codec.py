"""Wire encoding and decoding for a task bead's snooze record.

``snooze`` crosses the same three storage surfaces ``close_history`` does:
the Rust outcome dicts read by :mod:`sase.core.bead_wire`, the
``issues.jsonl`` rows written by :mod:`sase.bead.jsonl`, and the JSON column
in the compatibility SQLite mirror. They share this codec so a record cannot
mean one thing in one surface and something else in another.

Key order and omitted-when-absent optional keys mirror ``BeadSnoozeWire`` in
sase-core so a row this module writes is byte-identical to the Rust writer's.
"""

from __future__ import annotations

from typing import Any

from sase.bead.model import SnoozeRecord


def snooze_to_dict(record: SnoozeRecord) -> dict[str, Any]:
    """Encode one snooze record in sase-core wire field order."""
    return {
        "until": record.until,
        "snoozed_at": record.snoozed_at,
        "snoozed_by": record.snoozed_by,
        **(
            {"plus_one_target": record.plus_one_target}
            if record.plus_one_target is not None
            else {}
        ),
        **(
            {"plus_one_baseline": record.plus_one_baseline}
            if record.plus_one_baseline is not None
            else {}
        ),
        "reason": record.reason,
    }


def snooze_from_dict(value: object) -> SnoozeRecord | None:
    """Decode a snooze record, tolerating absence and unusable payloads.

    A payload that is not a mapping decodes to ``None`` rather than raising:
    every caller here is reading persisted state, and a bead that cannot be
    listed at all is worse than one whose wake conditions are unreadable.
    """
    if not isinstance(value, dict):
        return None
    return SnoozeRecord(
        until=str(value.get("until", "")),
        snoozed_at=str(value.get("snoozed_at", "")),
        snoozed_by=str(value.get("snoozed_by", "")),
        plus_one_target=_optional_int(value.get("plus_one_target")),
        plus_one_baseline=_optional_int(value.get("plus_one_baseline")),
        reason="" if value.get("reason") is None else str(value["reason"]),
    )


def _optional_int(value: object) -> int | None:
    if value is None:
        return None
    try:
        return int(value)  # type: ignore[call-overload]
    except (TypeError, ValueError):
        return None


__all__ = [
    "snooze_from_dict",
    "snooze_to_dict",
]
