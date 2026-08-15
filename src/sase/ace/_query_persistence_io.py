"""Shared write-then-read validation for the pane-keyed query stores."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any


def write_json_validated(path: Path, payload: dict[str, Any]) -> bool:
    """Write *payload* to *path* and read it back to confirm the write landed.

    Used by the query-persistence stores' read-time migration so a legacy
    file is never deleted or truncated on a failed write: the caller's
    in-memory result is correct for the current call either way, and a
    write that can't be proven durable is simply retried on the next load.
    """
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        encoded = json.dumps(payload, indent=2)
        path.write_text(encoded)
        return json.loads(path.read_text()) == payload
    except (OSError, json.JSONDecodeError):
        return False


__all__ = ["write_json_validated"]
