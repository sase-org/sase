"""Capture dispositions that can block automatic continuation dispatch."""

from __future__ import annotations

from collections.abc import Mapping, MutableMapping
import os
from typing import Any

from ._storage import update_agent_meta_fields

CAPTURE_DISPOSITION_OK = "ok"
CAPTURE_DISPOSITION_NEEDS_RECOVERY = "needs_recovery"


def record_capture_disposition(
    artifacts_dir: str | os.PathLike[str],
    *,
    disposition: str,
    error: str | None = None,
    meta: MutableMapping[str, Any] | None = None,
) -> None:
    """Record whether essential continuation capture succeeded."""

    fields: dict[str, Any] = {"continuation_capture_disposition": disposition}
    if error:
        fields["continuation_capture_error"] = error[:2000]
    if meta is not None:
        meta.update(fields)
    update_agent_meta_fields(artifacts_dir, fields)


def continuation_dispatch_blocked_reason(meta: Mapping[str, Any]) -> str | None:
    """Return the recovery reason that must block automatic dispatch, if any."""

    next_action = meta.get("monitor_next_action")
    if not (isinstance(next_action, str) and next_action.strip()):
        return None
    disposition = meta.get("continuation_capture_disposition")
    if disposition != CAPTURE_DISPOSITION_NEEDS_RECOVERY:
        return None
    error = meta.get("continuation_capture_error")
    if isinstance(error, str) and error:
        return error
    return (
        "essential continuation capture failed; automatic dispatch is blocked "
        "pending `sase monitor resume`"
    )


__all__ = [
    "CAPTURE_DISPOSITION_NEEDS_RECOVERY",
    "CAPTURE_DISPOSITION_OK",
    "continuation_dispatch_blocked_reason",
    "record_capture_disposition",
]
