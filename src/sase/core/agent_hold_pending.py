"""Pending-candidate capture helpers for durable agent holds."""

from __future__ import annotations

import logging
from collections.abc import Mapping
from typing import Any

from sase.core.agent_hold_types import PendingCapture

LOGGER = logging.getLogger(__name__)


def capture_pending_targets(
    *,
    project: str | None,
    armer: Mapping[str, Any] | None = None,
    scope: str = "project",
) -> PendingCapture:
    """Snapshot WAITING/QUEUED artifact dirs to freeze as a ``pending`` selector.

    Counts and frozen dirs come from effective capturable identities after
    scope and armer/kin exclusion. ``pending`` still does not capture
    undispatched procs. ``project`` scopes the scan the same way the hold's
    own scope will: a project-scoped hold only freezes that project's pending
    agents, while a host-scoped hold (``project=None``) freezes every
    project's.
    """
    from sase.agent.status_buckets import QUEUED_STATUS
    from sase.core.rust import require_rust_binding
    from sase.integrations.agent_list_entries import agent_list_entries

    scan_project = project if scope == "project" else None
    identities: list[dict[str, Any]] = []
    for entry in agent_list_entries(project=scan_project):
        status = getattr(entry, "status", "") or ""
        if status == "WAITING":
            bucket = "waiting"
        elif status == QUEUED_STATUS:
            bucket = "queued"
        else:
            bucket = "running"
        timestamp = getattr(entry, "timestamp", None)
        created_at = _entry_created_at(
            timestamp if isinstance(timestamp, str) else None
        )
        identities.append(
            {
                "project": getattr(entry, "project", None) or (project or ""),
                "created_at": created_at,
                "bucket": bucket,
                "artifact_dir": getattr(entry, "artifacts_dir", None),
                "agent_name": getattr(entry, "name", None),
                "family": getattr(entry, "agent_family", None),
                "clan": getattr(entry, "agent_clan", None),
            }
        )
    summarize = require_rust_binding("agent_hold_summarize_capture")
    scope_wire: dict[str, Any] = (
        {"kind": "host"}
        if scope == "host" or not project
        else {"kind": "project", "project": project}
    )
    result = summarize(
        scope_wire, identities, dict(armer) if armer is not None else None
    )
    if not isinstance(result, Mapping):
        raise RuntimeError("agent_hold_summarize_capture returned a non-object summary")
    summary = result.get("summary")
    if not isinstance(summary, Mapping):
        raise RuntimeError("agent hold capture summary is not an object")
    artifact_dirs = result.get("artifact_dirs") or []
    return PendingCapture(
        artifact_dirs=tuple(str(path) for path in artifact_dirs),
        waiting_count=int(summary.get("waiting_count") or 0),
        queued_count=int(summary.get("queued_count") or 0),
        skipped_running_count=int(summary.get("skipped_running_count") or 0),
    )


def preview_pending_capture(
    scope: str,
    *,
    project: str | None,
    armer: Mapping[str, Any] | None = None,
) -> PendingCapture | None:
    """Fail-soft snapshot of what a ``pending`` hold would freeze right now.

    Read-only launch previews call this, so a broken hold-adjacent scan must
    never break preview rendering the way :func:`capture_pending_targets`
    is allowed to raise for the direct arm path.
    """
    try:
        return capture_pending_targets(
            project=project if scope == "project" else None,
            armer=armer,
            scope=scope,
        )
    except Exception as exc:  # noqa: BLE001 - preview capture is fail-soft.
        LOGGER.warning("pending hold capture preview failed: %s", exc)
        return None


def format_pending_capture(capture: PendingCapture | None) -> str | None:
    """Return e.g. ``"captures 4 waiting + 2 queued; skips 3 running"``."""
    if capture is None:
        return None
    return (
        f"captures {capture.waiting_count} waiting + {capture.queued_count} queued; "
        f"skips {capture.skipped_running_count} running"
    )


def _entry_created_at(timestamp: str | None) -> float:
    from sase.core.agent_hold_facade import candidate_created_at_from_timestamp

    created_at = candidate_created_at_from_timestamp(timestamp)
    return created_at if created_at is not None else 1.0


def format_stored_capture(record: Mapping[str, Any] | None) -> str:
    """Render the arm-time capture stored on a hold, or an honest unknown."""
    if record is None:
        return "capture not recorded"
    raw = record.get("capture")
    if not isinstance(raw, Mapping):
        return "capture not recorded"
    try:
        waiting = int(raw["waiting_count"])
        queued = int(raw["queued_count"])
        skipped = int(raw["skipped_running_count"])
    except (KeyError, TypeError, ValueError):
        return "capture not recorded"
    return f"{waiting} waiting + {queued} queued; skipped {skipped} running"
