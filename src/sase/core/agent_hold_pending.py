"""Pending-candidate capture helpers for durable agent holds."""

from __future__ import annotations

import logging

from sase.core.agent_hold_types import PendingCapture

LOGGER = logging.getLogger(__name__)


def capture_pending_targets(*, project: str | None) -> PendingCapture:
    """Snapshot WAITING/QUEUED artifact dirs to freeze as a ``pending`` selector.

    ``project`` scopes the snapshot the same way the hold's own scope will:
    a project-scoped hold only freezes that project's pending agents, while
    a host-scoped hold (``project=None``) freezes every project's.
    """
    from sase.agent.status_buckets import QUEUED_STATUS
    from sase.integrations.agent_list_entries import agent_list_entries

    artifact_dirs: list[str] = []
    waiting_count = 0
    queued_count = 0
    skipped_running_count = 0
    for entry in agent_list_entries(project=project):
        if entry.status == "WAITING":
            waiting_count += 1
            if entry.artifacts_dir:
                artifact_dirs.append(entry.artifacts_dir)
        elif entry.status == QUEUED_STATUS:
            queued_count += 1
            if entry.artifacts_dir:
                artifact_dirs.append(entry.artifacts_dir)
        else:
            skipped_running_count += 1
    return PendingCapture(
        artifact_dirs=tuple(artifact_dirs),
        waiting_count=waiting_count,
        queued_count=queued_count,
        skipped_running_count=skipped_running_count,
    )


def preview_pending_capture(
    scope: str, *, project: str | None
) -> PendingCapture | None:
    """Fail-soft snapshot of what a ``pending`` hold would freeze right now.

    Read-only launch previews call this, so a broken hold-adjacent scan must
    never break preview rendering the way :func:`capture_pending_targets`
    is allowed to raise for the direct arm path.
    """
    try:
        return capture_pending_targets(project=project if scope == "project" else None)
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
