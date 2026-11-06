"""Notification and dismissal actions for terminal workspace retention."""

from __future__ import annotations

import logging
from collections.abc import Sequence
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any
from uuid import uuid4

from sase.core.workspace_retention import (
    DISPOSITION_RELEASE,
    WORKSPACE_RETENTION_WIRE_SCHEMA_VERSION,
    decide_workspace_retention_dismissal,
)
from sase.workspace_provider.occupant import clear_owned_occupant_record

if TYPE_CHECKING:
    from .workspace_retention import WorkspaceRetentionOwner

log = logging.getLogger(__name__)


def dismiss_terminal_workspace_retention(
    project_file: str,
    artifacts_dir: str | Path,
) -> bool | None:
    """Release an explicitly dismissed terminal hold after Rust checks identity.

    ``None`` means no terminal retention record exists and callers may use
    their legacy dismissal path. ``False`` means a record exists but it is
    settled, malformed, or no longer owns the claim.
    """
    from sase.workspace_provider.retention_record import (
        mark_workspace_retention_settled,
        read_workspace_retention_record,
    )
    from sase.core.time import get_timezone

    record = read_workspace_retention_record(artifacts_dir)
    if record is None:
        return None
    if not record.terminal or not record.unresolved:
        return False
    expected = _record_claim_wire(record)
    if expected is None:
        return False
    decision = decide_workspace_retention_dismissal(
        {
            "schema_version": WORKSPACE_RETENTION_WIRE_SCHEMA_VERSION,
            "expected_claim": expected,
            "observed_claim": _observed_record_claim(project_file, expected),
            "terminal_record": record.terminal,
            "unresolved": record.unresolved,
        }
    )
    if str(decision.get("disposition") or "") != DISPOSITION_RELEASE:
        return False
    from sase.running_field import release_workspace

    released = release_workspace(
        project_file,
        int(expected["workspace_num"]),
        str(expected["workflow"]),
        str(expected["cl_name"]),
        caller_tag="dismiss-workspace-retention",
        expected_pid=int(expected["pid"]),
        artifacts_timestamp=str(expected["artifacts_timestamp"]),
    )
    if not released.success:
        return False
    if record.workspace_dir:
        clear_owned_occupant_record(
            record.workspace_dir,
            int(expected["pid"]),
            artifacts_timestamp=str(expected["artifacts_timestamp"]) or None,
            workflow=str(expected["workflow"]),
            cl_name=str(expected["cl_name"]) or None,
            workspace_num=int(expected["workspace_num"]),
        )
    mark_workspace_retention_settled(
        artifacts_dir,
        reason="dismissed",
        settled_at=datetime.now(get_timezone()).isoformat(),
    )
    return True


def notify_retained_workspace(
    owner: WorkspaceRetentionOwner,
    record_path: str,
    snapshot_paths: Sequence[str],
) -> None:
    """Publish one retry-safe recovery notification for late monitor/gate holds."""
    try:
        import hashlib

        from sase.core.time import get_timezone
        from sase.notifications.models import Notification, normalize_notification_tags
        from sase.notifications.store import upsert_notification
        from sase.workspace_provider.retention_record import (
            configured_held_claim_ttl_days,
            read_workspace_retention_record,
            workspace_retention_lines,
        )

        record = read_workspace_retention_record(owner.artifacts_dir)
        if record is None or not record.unresolved:
            return
        timestamp = datetime.now(get_timezone()).isoformat()
        project_key = hashlib.sha256(owner.project_file.encode()).hexdigest()[:16]
        notification = Notification(
            id=str(uuid4()),
            timestamp=timestamp,
            sender="user-agent",
            notes=list(
                workspace_retention_lines(
                    record,
                    held_claim_ttl_days=configured_held_claim_ttl_days(),
                )
            ),
            files=list(dict.fromkeys([record_path, *snapshot_paths])),
            tags=normalize_notification_tags(["done", "workspace-held"]),
            action="JumpToAgent",
            action_data={
                "patch_name": owner.cl_name,
                "cl_name": owner.cl_name,
                "raw_suffix": owner.artifacts_timestamp,
            },
            dedup_key=(
                f"workspace-retention:{project_key}:{owner.artifacts_timestamp}:"
                f"{owner.workspace_num}"
            ),
        )
        upsert_notification(
            notification,
            plus_one_note=(
                "Workspace still held "
                f"({record.policy_reason or record.terminal_reason})"
            ),
            plus_one_timestamp=timestamp,
        )
    except Exception:
        log.warning("Could not publish workspace-retention notification", exc_info=True)


def _record_claim_wire(record: Any) -> dict[str, Any] | None:
    values = (
        record.workspace_num,
        record.workflow,
        record.cl_name,
        record.artifacts_timestamp,
        record.pid,
    )
    if (
        not isinstance(values[0], int)
        or not isinstance(values[1], str)
        or not values[1]
        or not isinstance(values[3], str)
        or not values[3]
        or not isinstance(values[4], int)
    ):
        return None
    return {
        "workspace_num": values[0],
        "workflow": values[1],
        "cl_name": values[2] if isinstance(values[2], str) else "",
        "artifacts_timestamp": values[3],
        "pid": values[4],
    }


def _observed_record_claim(
    project_file: str,
    expected: dict[str, Any],
) -> dict[str, Any] | None:
    from sase.running_field import get_claimed_workspaces

    try:
        claims = get_claimed_workspaces(project_file)
    except OSError:
        return None
    for claim in claims:
        if claim.workspace_num != expected["workspace_num"]:
            continue
        return {
            "workspace_num": claim.workspace_num,
            "workflow": claim.workflow,
            "cl_name": claim.cl_name or "",
            "artifacts_timestamp": claim.artifacts_timestamp or "",
            "pid": claim.pid,
        }
    return None


__all__ = ["dismiss_terminal_workspace_retention", "notify_retained_workspace"]
