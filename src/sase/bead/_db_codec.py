"""JSON column codecs for the compatibility bead mirror."""

from __future__ import annotations

import json

from sase.bead.close_history_codec import (
    close_history_from_dicts,
    close_history_to_dicts,
)
from sase.bead.model import CloseRecord, SnoozeRecord, TaskPlusOneEvidence
from sase.bead.snooze_codec import snooze_from_dict, snooze_to_dict


def plus_one_evidence_json(evidence: list[TaskPlusOneEvidence]) -> str:
    return json.dumps(
        [
            {
                "timestamp": entry.timestamp,
                "reporter": entry.reporter,
                "note": entry.note,
                "refs": list(entry.refs),
            }
            for entry in evidence
        ],
        separators=(",", ":"),
        ensure_ascii=False,
    )


def close_history_json(history: list[CloseRecord]) -> str:
    return json.dumps(
        close_history_to_dicts(history),
        separators=(",", ":"),
        ensure_ascii=False,
    )


def snooze_json(record: SnoozeRecord | None) -> str | None:
    """Encode a snooze record for the mirror, or ``None`` when absent."""
    if record is None:
        return None
    return json.dumps(
        snooze_to_dict(record),
        separators=(",", ":"),
        ensure_ascii=False,
    )


def snooze_from_json(value: object) -> SnoozeRecord | None:
    if value in (None, ""):
        return None
    try:
        record = json.loads(str(value))
    except (json.JSONDecodeError, TypeError, ValueError):
        return None
    return snooze_from_dict(record)


def close_history_from_json(value: object) -> list[CloseRecord]:
    try:
        records = json.loads(str(value or "[]"))
    except (json.JSONDecodeError, TypeError, ValueError):
        return []
    return close_history_from_dicts(records)


def plus_one_evidence_from_json(value: object) -> list[TaskPlusOneEvidence]:
    try:
        records = json.loads(str(value or "[]"))
    except (json.JSONDecodeError, TypeError, ValueError):
        return []
    if not isinstance(records, list):
        return []
    return [
        TaskPlusOneEvidence(
            timestamp=str(record.get("timestamp", "")),
            reporter=str(record.get("reporter", "")),
            note=str(record.get("note", "")),
            refs=tuple(str(ref) for ref in record.get("refs", [])),
        )
        for record in records
        if isinstance(record, dict)
    ]
