"""Terminal-blocker detection and notification for wait_checks."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any
from uuid import uuid4

from sase.core.time import get_timezone
from sase.core.wait_dependency_resolution import (
    WaitDependencyIndex,
    read_json_dict as _read_json_dict,
)
from sase.core.wait_dependency_resolution._types import ArtifactCandidate
from sase.notifications.models import Notification, normalize_notification_tags
from sase.notifications.store import upsert_notification
from sase.scripts._chop_wait_checks_common import TerminalBlocker, WaitingMarker

_TERMINAL_BLOCKED_WAIT_SENDER = "wait_checks"


def terminal_blockers(
    dependency_index: WaitDependencyIndex,
    waiting_for: list[object],
    wait_for_artifacts: list[object],
    wait_for_hoods: list[object],
    blocked_on: tuple[str, ...],
    *,
    self_artifact_dir: Path,
) -> tuple[TerminalBlocker, ...]:
    blocked_labels = frozenset(blocked_on)
    blockers: list[TerminalBlocker] = []
    identity_names: set[str] = set()

    for dependency in wait_for_artifacts:
        if not isinstance(dependency, Mapping):
            continue
        name = dependency.get("name")
        if isinstance(name, str) and name:
            identity_names.add(name)
        label = _dependency_label(dependency)
        if label not in blocked_labels:
            continue
        candidate = _artifact_candidate_for_identity(dependency_index, dependency)
        if candidate is not None and _identity_terminal_blocker(candidate):
            outcome = candidate.outcome
            assert outcome is not None
            blockers.append(
                TerminalBlocker(
                    dependency=label,
                    artifact_dir=candidate.artifact_dir,
                    outcome=outcome,
                )
            )

    waiter_launch_cutoff = self_artifact_dir.name
    for hood in wait_for_hoods:
        if not isinstance(hood, str):
            continue
        label = f"hood={hood}"
        if label not in blocked_labels:
            continue
        for candidate in dependency_index.terminal_blocking_artifacts_for_hood(
            hood,
            exclude_artifact_dir=self_artifact_dir,
            launched_at_or_before=waiter_launch_cutoff,
        ):
            assert candidate.outcome is not None
            blockers.append(
                TerminalBlocker(
                    dependency=label,
                    artifact_dir=candidate.artifact_dir,
                    outcome=candidate.outcome,
                )
            )

    for name in waiting_for:
        if not isinstance(name, str) or name in identity_names:
            continue
        if name not in blocked_labels:
            continue
        for candidate in dependency_index.terminal_blocking_artifacts_for_name(
            name,
            exclude_artifact_dir=self_artifact_dir,
            newer_than=waiter_launch_cutoff if name.startswith("@") else None,
        ):
            assert candidate.outcome is not None
            blockers.append(
                TerminalBlocker(
                    dependency=name,
                    artifact_dir=candidate.artifact_dir,
                    outcome=candidate.outcome,
                )
            )

    return tuple(blockers)


def upsert_terminal_blocked_wait_notification(
    waiting_marker: WaitingMarker,
    waiting_data: Mapping[str, Any],
    blocker: TerminalBlocker,
) -> None:
    waiter_dir = waiting_marker.waiting_path.parent
    waiter_name = _waiting_agent_label(waiting_data, waiter_dir)
    timestamp = datetime.now(get_timezone()).isoformat()
    recovery = _monitor_not_launchable_recovery(blocker.artifact_dir)
    notes = [
        "Wait dependency can never self-resolve",
        f"Waiter: {waiter_name}",
        (
            f"Blocked on {blocker.dependency}: {blocker.artifact_dir} "
            f"({blocker.outcome})"
        ),
        (
            "Kill and relaunch the waiter, or intentionally clear the wait "
            "once the dependency state is understood."
        ),
    ]
    files = [str(waiter_dir), blocker.artifact_dir]
    # `action_data` stays empty: every producer value already lives in
    # `notes` (waiter, dependency, outcome, recovery instructions) or
    # `files` (waiter/blocking dirs, recovery diff) for display and search.
    # No consumer reads `wait_checks` action keys to drive an action.
    if recovery.resume_command:
        notes.append(f"Monitor recovery: `{recovery.resume_command}`")
    if recovery.snapshot_path:
        notes.append(f"Worktree recovery diff: {recovery.snapshot_path}")
        files.append(recovery.snapshot_path)
    notification = Notification(
        id=str(uuid4()),
        timestamp=timestamp,
        sender=_TERMINAL_BLOCKED_WAIT_SENDER,
        icon="!",
        color="#D14343",
        notes=notes,
        files=files,
        tags=normalize_notification_tags(["wait", "blocked", "terminal-dependency"]),
        dedup_key=f"wait_checks:terminal-blocked:{waiter_dir}",
    )
    upsert_notification(
        notification,
        plus_one_note=(
            f"Still blocked on {blocker.dependency}: {blocker.artifact_dir} "
            f"({blocker.outcome})"
        ),
        plus_one_timestamp=timestamp,
    )


@dataclass(frozen=True)
class _MonitorRecovery:
    resume_command: str | None = None
    snapshot_path: str | None = None


def _monitor_not_launchable_recovery(artifact_dir: str) -> _MonitorRecovery:
    done = _read_json_dict(Path(artifact_dir) / "done.json")
    if done is None or done.get("monitor_followup_outcome") != "not-launchable":
        return _MonitorRecovery()
    meta = _read_json_dict(Path(artifact_dir) / "agent_meta.json") or {}
    monitor_id = _string_value(done.get("monitor_id")) or _string_value(
        meta.get("monitor_id")
    )
    snapshot_path = _string_value(
        done.get("monitor_worktree_recovery_diff_path")
    ) or _string_value(meta.get("monitor_worktree_recovery_diff_path"))
    return _MonitorRecovery(
        resume_command=f"sase monitor resume {monitor_id}" if monitor_id else None,
        snapshot_path=snapshot_path,
    )


def _string_value(value: object) -> str | None:
    return value if isinstance(value, str) and value else None


def _waiting_agent_label(waiting_data: Mapping[str, Any], waiter_dir: Path) -> str:
    cl_name = waiting_data.get("cl_name")
    if isinstance(cl_name, str) and cl_name:
        return cl_name
    return waiter_dir.name


def _artifact_candidate_for_identity(
    dependency_index: WaitDependencyIndex,
    dependency: Mapping[str, Any],
) -> ArtifactCandidate | None:
    artifact_dir = dependency.get("artifact_dir")
    if isinstance(artifact_dir, str) and artifact_dir:
        candidate = dependency_index.artifacts_by_dir.get(artifact_dir)
        if candidate is not None:
            return candidate

    project_name = dependency.get("project_name")
    timestamp = dependency.get("timestamp")
    if isinstance(project_name, str) and isinstance(timestamp, str):
        return dependency_index.artifacts.get((project_name, timestamp))
    return None


def _identity_terminal_blocker(candidate: ArtifactCandidate) -> bool:
    return (
        candidate.has_done_marker
        and candidate.outcome is not None
        and not candidate.is_identity_success
    )


def _dependency_label(dependency: Mapping[str, Any]) -> str:
    artifact_dir = dependency.get("artifact_dir")
    if isinstance(artifact_dir, str) and artifact_dir:
        return artifact_dir
    project_name = dependency.get("project_name")
    timestamp = dependency.get("timestamp")
    if (
        isinstance(project_name, str)
        and project_name
        and isinstance(timestamp, str)
        and timestamp
    ):
        return f"{project_name}:{timestamp}"
    name = dependency.get("name")
    if isinstance(name, str) and name:
        return name
    return "<artifact dependency>"


__all__ = [
    "terminal_blockers",
    "upsert_terminal_blocked_wait_notification",
]
