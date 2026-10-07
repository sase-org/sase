"""Wait release telemetry: when the last dependency member finished.

``latest_member_finished_at`` backs the ``release-telemetry`` phase: it lets
``wait_checks`` and the runner stamp ``wait_dependencies_satisfied_at`` (and
the derived ``wait_release_latency_s``) from the members' ``done.json``
``finished_at`` markers.
"""

from __future__ import annotations

import json
import math
import os
from collections.abc import Iterable
from datetime import datetime
from typing import Any


def parse_finished_at(value: Any) -> float | None:
    """Return an epoch-seconds timestamp for a ``done.json`` value.

    Accepts numeric epochs and strings holding either a float or an ISO 8601
    timestamp. Returns ``None`` for anything else (missing, bools, malformed
    text, non-finite floats).
    """
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        result = float(value)
        return result if math.isfinite(result) else None
    if isinstance(value, str):
        text = value.strip()
        if not text:
            return None
        try:
            result = float(text)
        except ValueError:
            pass
        else:
            return result if math.isfinite(result) else None
        try:
            parsed = datetime.fromisoformat(text)
        except ValueError:
            return None
        result = parsed.timestamp()
        return result if math.isfinite(result) else None
    return None


def latest_member_finished_at(
    member_dirs: Iterable[str | os.PathLike[str]],
) -> float | None:
    """Return the max numeric ``finished_at`` across member ``done.json`` files.

    Members without a readable ``done.json`` (or without a parseable
    ``finished_at``) are ignored. Returns ``None`` when nothing is known.
    """
    latest: float | None = None
    for member in member_dirs:
        try:
            with open(os.path.join(str(member), "done.json"), encoding="utf-8") as f:
                data = json.load(f)
        except (OSError, json.JSONDecodeError, UnicodeDecodeError):
            continue
        if not isinstance(data, dict):
            continue
        finished = parse_finished_at(data.get("finished_at"))
        if finished is not None and (latest is None or finished > latest):
            latest = finished
    return latest
