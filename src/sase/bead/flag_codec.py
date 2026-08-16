"""Wire encoding and decoding for a flag bead's removal record.

``flag`` crosses the same three storage surfaces ``snooze`` does: the Rust
outcome dicts read by :mod:`sase.core.bead_wire`, the ``issues.jsonl`` rows
written by :mod:`sase.bead.jsonl`, and the JSON column in the compatibility
SQLite mirror. They share this codec so a record cannot mean one thing in one
surface and something else in another.

Key order mirrors ``BeadFlagWire`` in sase-core so a row this module writes is
byte-identical to the Rust writer's.
"""

from __future__ import annotations

from typing import Any

from sase.bead.model import FlagRecord


def flag_to_dict(record: FlagRecord) -> dict[str, Any]:
    """Encode one flag record in sase-core wire field order."""
    return {
        "key": record.key,
        "remove_by_date": record.remove_by_date,
        "remove_by_release": record.remove_by_release,
    }


def flag_from_dict(value: object) -> FlagRecord | None:
    """Decode a flag record, tolerating absence and unusable payloads.

    A payload that is not a mapping decodes to ``None`` rather than raising:
    every caller here is reading persisted state, and a bead that cannot be
    listed at all is worse than one whose removal thresholds are unreadable.
    """
    if not isinstance(value, dict):
        return None
    return FlagRecord(
        key=str(value.get("key", "")),
        remove_by_date=str(value.get("remove_by_date", "")),
        remove_by_release=str(value.get("remove_by_release", "")),
    )


__all__ = [
    "flag_from_dict",
    "flag_to_dict",
]
