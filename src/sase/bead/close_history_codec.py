"""Wire encoding and decoding for archived bead close records.

``close_history`` crosses three storage surfaces that all speak the same
record shape: the Rust outcome dicts read by :mod:`sase.core.bead_wire`, the
``issues.jsonl`` rows written by :mod:`sase.bead.jsonl`, and the JSON column
in the compatibility SQLite mirror. They share this codec so a record cannot
mean one thing in one surface and something else in another.

Key order and omitted-when-absent optional keys mirror ``BeadCloseRecordWire``
in sase-core so a row this module writes is byte-identical to the Rust writer's.
"""

from __future__ import annotations

from typing import Any

from sase.bead.model import (
    BeadCloseProvenance,
    CloseRecord,
    ReopenCause,
    Resolution,
)


def _provenance_to_dict(provenance: BeadCloseProvenance) -> dict[str, Any]:
    """Encode close provenance in sase-core wire field order."""
    return {
        "run_id": provenance.run_id,
        "agent_name": provenance.agent_name,
        "artifact_dir": provenance.artifact_dir,
    }


def provenance_from_dict(value: object) -> BeadCloseProvenance | None:
    """Decode close provenance, tolerating absence but not junk."""
    if value is None:
        return None
    if not isinstance(value, dict):
        raise ValueError("close provenance must be a mapping")
    return BeadCloseProvenance(
        run_id=str(value.get("run_id", "")),
        agent_name=str(value.get("agent_name", "")),
        artifact_dir=str(value.get("artifact_dir", "")),
    )


def _close_record_to_dict(record: CloseRecord) -> dict[str, Any]:
    """Encode one archived close record in sase-core wire field order."""
    return {
        "closed_at": record.closed_at,
        **({"close_reason": record.close_reason} if record.close_reason else {}),
        **({"resolution": record.resolution.value} if record.resolution else {}),
        "reopened_at": record.reopened_at,
        "reopened_via": record.reopened_via.value,
        **({"reopened_by": record.reopened_by} if record.reopened_by else {}),
        **({"close_event_id": record.close_event_id} if record.close_event_id else {}),
        **(
            {"close_provenance": _provenance_to_dict(record.close_provenance)}
            if record.close_provenance is not None
            else {}
        ),
    }


def close_history_to_dicts(history: list[CloseRecord]) -> list[dict[str, Any]]:
    return [_close_record_to_dict(record) for record in history]


def close_history_from_dicts(value: object) -> list[CloseRecord]:
    """Decode archived close records, tolerating absence and junk entries.

    A record with an unknown ``reopened_via`` is dropped rather than raising:
    every caller here is reading persisted state that a newer sase-core may
    have written, and a bead that cannot be listed at all is worse than one
    missing an archived episode.
    """
    if not isinstance(value, list):
        return []
    records: list[CloseRecord] = []
    for entry in value:
        if not isinstance(entry, dict):
            continue
        try:
            reopened_via = ReopenCause(str(entry.get("reopened_via", "")))
        except ValueError:
            continue
        resolution_raw = entry.get("resolution")
        try:
            resolution = Resolution(str(resolution_raw)) if resolution_raw else None
        except ValueError:
            resolution = None
        close_reason = entry.get("close_reason")
        reopened_by = entry.get("reopened_by")
        close_event_id = entry.get("close_event_id")
        records.append(
            CloseRecord(
                closed_at=str(entry.get("closed_at", "")),
                reopened_at=str(entry.get("reopened_at", "")),
                reopened_via=reopened_via,
                close_reason=None if close_reason is None else str(close_reason),
                resolution=resolution,
                reopened_by=None if reopened_by is None else str(reopened_by),
                close_event_id=None if close_event_id is None else str(close_event_id),
                close_provenance=provenance_from_dict(entry.get("close_provenance")),
            )
        )
    return records


__all__ = [
    "close_history_from_dicts",
    "close_history_to_dicts",
    "provenance_from_dict",
]
