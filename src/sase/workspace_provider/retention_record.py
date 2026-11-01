"""Typed reads and updates for terminal workspace-retention records."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from sase.core.atomic_json import write_json_marker_atomic

RETENTION_RECORD_LOCATOR = "diagnostics/workspace_retention.json"


@dataclass(frozen=True, slots=True)
class WorkspaceRetentionRecord:
    """Display and release facts persisted for one terminal workspace hold."""

    path: str
    payload: dict[str, Any]

    @property
    def workspace_num(self) -> int | None:
        value = self.payload.get("workspace_num")
        return value if isinstance(value, int) and not isinstance(value, bool) else None

    @property
    def workspace_dir(self) -> str | None:
        return _optional_string(self.payload.get("workspace_dir"))

    @property
    def workflow(self) -> str | None:
        return _optional_string(self.payload.get("workflow"))

    @property
    def cl_name(self) -> str | None:
        return _optional_string(self.payload.get("cl_name"))

    @property
    def artifacts_timestamp(self) -> str | None:
        return _optional_string(self.payload.get("artifacts_timestamp"))

    @property
    def pid(self) -> int | None:
        value = self.payload.get("pid")
        return value if isinstance(value, int) and not isinstance(value, bool) else None

    @property
    def terminal_reason(self) -> str:
        return (
            _optional_string(self.payload.get("terminal_reason")) or "terminal handoff"
        )

    @property
    def policy_reason(self) -> str | None:
        return _optional_string(self.payload.get("policy_reason"))

    @property
    def disposition(self) -> str | None:
        return _optional_string(self.payload.get("disposition"))

    @property
    def origin_repo_ids(self) -> tuple[str, ...]:
        return _string_tuple(self.payload.get("origin_repo_ids"))

    @property
    def affected_repo_ids(self) -> tuple[str, ...]:
        return _string_tuple(self.payload.get("affected_repo_ids"))

    @property
    def snapshot_paths(self) -> tuple[str, ...]:
        return _string_tuple(self.payload.get("snapshot_paths"))

    @property
    def staged_id(self) -> str | None:
        return _optional_string(self.payload.get("staged_id"))

    @property
    def session_id(self) -> str | None:
        return _optional_string(self.payload.get("session_id"))

    @property
    def turn_id(self) -> str | None:
        return _optional_string(self.payload.get("turn_id"))

    @property
    def unresolved(self) -> bool:
        return self.disposition == "retain" and not self.payload.get("settled_at")

    @property
    def terminal(self) -> bool:
        return self.payload.get("kind") == "terminal_workspace_retention"


def read_workspace_retention_record(
    artifacts_dir: str | Path | None,
) -> WorkspaceRetentionRecord | None:
    """Read a valid terminal retention record; malformed and absent data is ignored."""
    if not artifacts_dir:
        return None
    path = Path(artifacts_dir) / RETENTION_RECORD_LOCATOR
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(value, dict):
        return None
    if value.get("kind") != "terminal_workspace_retention":
        return None
    return WorkspaceRetentionRecord(path=str(path), payload=value)


def mark_workspace_retention_settled(
    artifacts_dir: str | Path,
    *,
    reason: str,
    settled_at: str,
) -> bool:
    """Mark a retained record settled after its ownership-checked release."""
    record = read_workspace_retention_record(artifacts_dir)
    if record is None or not record.unresolved:
        return False
    payload = dict(record.payload)
    payload["settled_at"] = settled_at
    payload["settled_reason"] = reason
    try:
        write_json_marker_atomic(Path(record.path), payload)
    except OSError:
        return False
    return True


def configured_held_claim_ttl_days() -> int | None:
    """Read the existing held-claim TTL for recovery guidance."""
    try:
        from sase.config import load_merged_config
        from sase.workspace_provider.store import held_claim_ttl_days_from_config

        return held_claim_ttl_days_from_config(load_merged_config())
    except Exception:
        return None


def workspace_retention_lines(
    record: WorkspaceRetentionRecord,
    *,
    held_claim_ttl_days: int | None = None,
) -> tuple[str, ...]:
    """Format the terminal hold, recovery evidence, and existing actions."""
    identity = f"Workspace #{record.workspace_num or '?'}"
    if record.workspace_dir:
        identity += f" at {record.workspace_dir}"
    lines = [
        "Workspace held: stranded work",
        identity,
        f"Cause: {record.terminal_reason}",
    ]
    repositories = record.affected_repo_ids or record.origin_repo_ids
    if repositories:
        lines.append(f"Affected repositories: {', '.join(repositories)}")
    if record.snapshot_paths:
        lines.append("Best-effort recovery diffs: " + ", ".join(record.snapshot_paths))
    else:
        lines.append(
            "No recovery diff was captured; diff snapshots are best-effort and the "
            "held checkout preserves the work."
        )
    if record.staged_id:
        lines.append(
            f"Staged handoff {record.staged_id} remains available for re-adoption; "
            "dismiss this agent to release the workspace."
        )
    elif record.workflow == "ace-monitor" and record.turn_id:
        lines.append(
            f"Resume with `sase monitor resume {record.turn_id}`, or dismiss this "
            "agent to release the workspace."
        )
    else:
        lines.append("Dismiss this agent to release the workspace.")
    if held_claim_ttl_days is None:
        lines.append(
            "Recovery evidence is best-effort. A dead-PID hold follows the configured "
            "held-claim expiry policy."
        )
    elif held_claim_ttl_days <= 0:
        lines.append(
            "Recovery evidence is best-effort. Automatic dead-PID hold expiry is "
            "disabled; dismiss the agent to release the workspace."
        )
    else:
        lines.append(
            f"Recovery evidence is best-effort. A dead-PID hold expires after "
            f"{held_claim_ttl_days} days; a live claim stays held until "
            "dismissed."
        )
    return tuple(lines)


def _optional_string(value: object) -> str | None:
    return value.strip() if isinstance(value, str) and value.strip() else None


def _string_tuple(value: object) -> tuple[str, ...]:
    if not isinstance(value, list):
        return ()
    return tuple(
        item.strip() for item in value if isinstance(item, str) and item.strip()
    )


__all__ = [
    "RETENTION_RECORD_LOCATOR",
    "WorkspaceRetentionRecord",
    "configured_held_claim_ttl_days",
    "mark_workspace_retention_settled",
    "read_workspace_retention_record",
    "workspace_retention_lines",
]
