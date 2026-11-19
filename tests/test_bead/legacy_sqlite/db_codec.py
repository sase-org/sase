"""JSON column codecs for the compatibility bead mirror."""

from __future__ import annotations

import json

from sase.bead.close_history_codec import (
    close_history_from_dicts,
    close_history_to_dicts,
)
from sase.bead.model import BeadNote, CloseRecord, SnoozeRecord, TaskPlusOneEvidence
from sase.bead.note_codec import (
    LEGACY_NOTE_ID_PREFIX,
    _notes_from_dicts as notes_from_dicts,
    notes_to_dicts,
    _parse_legacy_note_blob as parse_legacy_note_blob,
)
from sase.bead.snooze_codec import snooze_from_dict
from typing import Any


def snooze_to_dict(record: SnoozeRecord) -> dict[str, Any]:
    """Encode one snooze record in sase-core wire field order (test-only copy).

    Retired from ``sase.bead.snooze_codec`` with the Python SQLite mirror;
    kept here so legacy fixture exports stay byte-identical to the Rust writer.
    """
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


def plus_one_evidence_json(evidence: list[TaskPlusOneEvidence]) -> str:
    from sase.bead.note_codec import attachment_to_dict as _evidence_attachment_to_dict

    return json.dumps(
        [
            {
                "timestamp": entry.timestamp,
                "reporter": entry.reporter,
                "note": entry.note,
                "refs": list(entry.refs),
                **(
                    {"observed_since": entry.observed_since}
                    if entry.observed_since
                    else {}
                ),
                **(
                    {
                        "attachments": [
                            _evidence_attachment_to_dict(a) for a in entry.attachments
                        ]
                    }
                    if entry.attachments
                    else {}
                ),
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


def notes_json(notes: list[BeadNote]) -> str:
    return json.dumps(
        notes_to_dicts(notes),
        separators=(",", ":"),
        ensure_ascii=False,
    )


def notes_from_json(
    value: object,
    *,
    fallback_timestamp: str = "",
    fallback_author: str = "",
) -> list[BeadNote]:
    """Decode the mirror's ``notes`` column.

    Tolerates a pre-migration row that still carries a plain-text blob
    (not valid JSON, or a JSON string) by recovering it the same way
    :func:`sase.bead.note_codec.notes_from_data` does for ``issues.jsonl``.
    """
    if value in (None, ""):
        return []
    try:
        parsed = json.loads(str(value))
    except (json.JSONDecodeError, TypeError, ValueError):
        return parse_legacy_note_blob(
            str(value), LEGACY_NOTE_ID_PREFIX, fallback_timestamp, fallback_author
        )
    if isinstance(parsed, str):
        return parse_legacy_note_blob(
            parsed, LEGACY_NOTE_ID_PREFIX, fallback_timestamp, fallback_author
        )
    return notes_from_dicts(parsed)


def task_type_fields_json(fields: dict[str, str]) -> str:
    return json.dumps(fields, separators=(",", ":"), ensure_ascii=False, sort_keys=True)


def task_type_fields_from_json(value: object) -> dict[str, str]:
    if value in (None, ""):
        return {}
    try:
        parsed = json.loads(str(value))
    except (json.JSONDecodeError, TypeError, ValueError):
        return {}
    if not isinstance(parsed, dict):
        return {}
    return {str(key): "" if item is None else str(item) for key, item in parsed.items()}


def plus_one_evidence_from_json(value: object) -> list[TaskPlusOneEvidence]:
    try:
        records = json.loads(str(value or "[]"))
    except (json.JSONDecodeError, TypeError, ValueError):
        return []
    if not isinstance(records, list):
        return []
    from sase.bead.note_codec import attachments_from_list as _attachments_from_list

    return [
        TaskPlusOneEvidence(
            timestamp=str(record.get("timestamp", "")),
            reporter=str(record.get("reporter", "")),
            note=str(record.get("note", "")),
            refs=tuple(str(ref) for ref in record.get("refs", [])),
            observed_since=(
                None
                if record.get("observed_since") is None
                else str(record.get("observed_since"))
            ),
            attachments=_attachments_from_list(record.get("attachments")),
        )
        for record in records
        if isinstance(record, dict)
    ]
