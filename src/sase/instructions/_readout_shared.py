"""Shared readout constants and helpers needed by more than one submodule.

Public names only: no ``_``-prefixed symbol is imported across the new
readout modules, so helpers shared by several of them live here as public
names inside this already-private module.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

READOUT_SCHEMA_VERSION = 1
TAIL_SCAN_BYTES = 262144

ACCEPTED = "accepted"
PLAN_HANDOFF = "plan_handoff"
MONITOR_PREPARED = "monitor_prepared"
MONITOR_PLAIN = "monitor_plain"
OTHER_HANDOFF = "other_handoff"
NOT_REQUIRED = "not_required"
MISS = "miss"
UNKNOWN = "unknown"

CLASSES = (
    ACCEPTED,
    PLAN_HANDOFF,
    MONITOR_PREPARED,
    MONITOR_PLAIN,
    OTHER_HANDOFF,
    NOT_REQUIRED,
    MISS,
    UNKNOWN,
)

EXPLICIT = "explicit"
LEGACY = "legacy"
NONE = "none"

MODES = (EXPLICIT, LEGACY, NONE)


def read_json(path: Path) -> dict[str, Any]:
    try:
        decoded = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return decoded if isinstance(decoded, dict) else {}


__all__ = [
    "ACCEPTED",
    "CLASSES",
    "EXPLICIT",
    "LEGACY",
    "MISS",
    "MODES",
    "MONITOR_PLAIN",
    "MONITOR_PREPARED",
    "NONE",
    "NOT_REQUIRED",
    "OTHER_HANDOFF",
    "PLAN_HANDOFF",
    "READOUT_SCHEMA_VERSION",
    "TAIL_SCAN_BYTES",
    "UNKNOWN",
    "read_json",
]
