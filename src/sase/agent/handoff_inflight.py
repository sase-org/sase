"""Archived in-flight and aborted-handoff readers.

In-agent handoff commands stage and return. This module no longer writes
in-flight markers, waits to adopt them, or records new aborts. Leftover
``.sase_handoff_inflight`` files and ``handoff_aborted.json`` records remain
readable for diagnosis and done-marker projection.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

HANDOFF_INFLIGHT_MARKER = ".sase_handoff_inflight"
HANDOFF_ABORTED_FILENAME = "handoff_aborted.json"


def load_handoff_aborted_record(
    artifacts_dir: str | None,
) -> dict[str, Any] | None:
    """Return a previously recorded ``handoff_aborted`` payload, if any."""
    if not artifacts_dir:
        return None
    try:
        raw = (Path(artifacts_dir) / HANDOFF_ABORTED_FILENAME).read_text(
            encoding="utf-8"
        )
    except OSError:
        return None
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError:
        return None
    return payload if isinstance(payload, dict) else None


def merge_handoff_aborted_into_done_marker(
    artifacts_dir: str,
    done_marker: dict[str, Any],
) -> dict[str, Any]:
    """Attach an on-disk ``handoff_aborted`` record to a done marker being built."""
    if "handoff_aborted" in done_marker:
        return done_marker
    record = load_handoff_aborted_record(artifacts_dir)
    if record is not None:
        done_marker["handoff_aborted"] = record
    return done_marker


__all__ = [
    "HANDOFF_ABORTED_FILENAME",
    "HANDOFF_INFLIGHT_MARKER",
    "load_handoff_aborted_record",
    "merge_handoff_aborted_into_done_marker",
]
