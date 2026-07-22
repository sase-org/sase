"""Atomic cached status with no-network local revalidation."""

from __future__ import annotations

from collections.abc import Sequence
import json
from pathlib import Path
import time
from typing import Any

from sase.agents_sync.bundles import count_unexported_local_agents
from sase.agents_sync.git import GitRunner, run_git
from sase.agents_sync.io import AgentsSyncFormatError, atomic_write_json, read_manifest
from sase.agents_sync.models import (
    STATUS_SCHEMA_VERSION,
    ProjectSyncStatus,
    ProjectTarget,
    StatusState,
    SyncOutcome,
    SyncStatusSnapshot,
)
from sase.agents_sync.targets import resolve_sync_targets
from sase.config import require_machine_name
from sase.core.paths import sase_home

DEFAULT_STATUS_TTL_SECONDS = 10 * 60


def _status_snapshot_path() -> Path:
    return sase_home() / "agents_sync" / "status_snapshot.json"


def get_agents_sync_status(
    projects: Sequence[str] = (),
    *,
    refresh: bool = False,
    revalidate_only: bool = False,
    now: float | None = None,
    ttl_seconds: float = DEFAULT_STATUS_TTL_SECONDS,
    git_runner: GitRunner = run_git,
    path: Path | None = None,
) -> SyncStatusSnapshot:
    """Return locally revalidated status, optionally refreshing remote refs.

    ``revalidate_only`` is the explicit no-network mode for periodic and
    preview callers. It recomputes local git and unexported-agent facts even
    when the cache is missing or stale, while preserving the last successful
    fetch timestamp. ``refresh`` remains the explicit forced-network mode.
    """

    if refresh and revalidate_only:
        raise ValueError("refresh and revalidate_only are mutually exclusive")

    checked_at = time.time() if now is None else now
    selection = resolve_sync_targets(projects)
    try:
        machine = require_machine_name()
    except (RuntimeError, ValueError) as exc:
        statuses = [_status_from_outcome(outcome) for outcome in selection.outcomes]
        statuses.extend(
            ProjectSyncStatus(
                target.project_key,
                target.project,
                "configuration_error",
                error=f"machine identity is not configured: {exc}",
            )
            for target in selection.targets
        )
        snapshot = SyncStatusSnapshot(checked_at, tuple(statuses))
        _write_agents_sync_status_snapshot(snapshot, path=path)
        return snapshot

    previous = _read_agents_sync_status_snapshot(path=path)
    fresh = previous is not None and _snapshot_is_fresh(
        previous, now=checked_at, ttl_seconds=ttl_seconds
    )
    fetch = not revalidate_only and (refresh or not fresh)
    previous_by_key = (
        {status.project_key: status for status in previous.projects}
        if previous is not None
        else {}
    )
    statuses = [_status_from_outcome(outcome) for outcome in selection.outcomes]
    for target in selection.targets:
        prior = previous_by_key.get(target.project_key)
        last_fetch = prior.last_fetch_time if prior is not None else None
        fetch_error: str | None = None
        if fetch and (target.sidecar_path / ".git").exists():
            fetched = git_runner(
                target.sidecar_path,
                ["fetch", "--prune", "origin"],
                network=True,
                op="agents_sync.status_fetch",
            )
            if fetched.returncode == 0:
                last_fetch = checked_at
            else:
                detail = (
                    fetched.stderr or fetched.stdout or "unknown git error"
                ).strip()
                fetch_error = f"git fetch failed: {detail}"
        status = _revalidate_project_status(
            target,
            machine,
            last_fetch_time=last_fetch,
            git_runner=git_runner,
        )
        if fetch_error is not None:
            status = ProjectSyncStatus(
                target.project_key,
                target.project,
                "error",
                ahead=status.ahead,
                behind=status.behind,
                unexported_agents=status.unexported_agents,
                last_fetch_time=last_fetch,
                detail=status.detail,
                error=fetch_error,
            )
        statuses.append(status)

    snapshot = SyncStatusSnapshot(
        checked_at,
        tuple(sorted(statuses, key=lambda item: item.project_key)),
    )
    _write_agents_sync_status_snapshot(snapshot, path=path)
    return snapshot


def _revalidate_project_status(
    target: ProjectTarget,
    machine: str,
    *,
    last_fetch_time: float | None,
    git_runner: GitRunner = run_git,
) -> ProjectSyncStatus:
    """Recompute local facts without any network access."""

    repo = target.sidecar_path
    if not (repo / ".git").exists():
        return ProjectSyncStatus(
            target.project_key,
            target.project,
            "not_created",
            last_fetch_time=last_fetch_time,
            detail="agents sidecar clone does not exist on this machine",
        )
    try:
        manifest = read_manifest(repo / "manifest.json")
    except AgentsSyncFormatError as exc:
        return ProjectSyncStatus(
            target.project_key,
            target.project,
            "error",
            last_fetch_time=last_fetch_time,
            error=str(exc),
        )
    upstream = git_runner(
        repo,
        ["rev-parse", "--verify", "@{upstream}"],
        op="agents_sync.status_upstream",
    )
    if upstream.returncode != 0:
        return ProjectSyncStatus(
            target.project_key,
            target.project,
            "missing_upstream",
            unexported_agents=count_unexported_local_agents(
                target, manifest, machine, git_runner=git_runner
            ),
            last_fetch_time=last_fetch_time,
            detail="agents sidecar clone has no configured upstream",
        )
    counts = git_runner(
        repo,
        ["rev-list", "--left-right", "--count", "HEAD...@{upstream}"],
        op="agents_sync.status_counts",
    )
    if counts.returncode != 0:
        detail = (counts.stderr or counts.stdout or "unknown git error").strip()
        return ProjectSyncStatus(
            target.project_key,
            target.project,
            "error",
            last_fetch_time=last_fetch_time,
            error=f"could not compare agents sidecar with upstream: {detail}",
        )
    try:
        ahead_raw, behind_raw = counts.stdout.split()
        ahead = int(ahead_raw)
        behind = int(behind_raw)
        unexported = count_unexported_local_agents(
            target, manifest, machine, git_runner=git_runner
        )
    except (ValueError, OSError, RuntimeError) as exc:
        return ProjectSyncStatus(
            target.project_key,
            target.project,
            "error",
            last_fetch_time=last_fetch_time,
            error=f"could not compute agents sync status: {exc}",
        )
    return ProjectSyncStatus(
        target.project_key,
        target.project,
        "ready",
        ahead=ahead,
        behind=behind,
        unexported_agents=unexported,
        last_fetch_time=last_fetch_time,
    )


def _read_agents_sync_status_snapshot(
    *, path: Path | None = None
) -> SyncStatusSnapshot | None:
    cache_path = path or _status_snapshot_path()
    try:
        raw = json.loads(cache_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, UnicodeDecodeError):
        return None
    if not isinstance(raw, dict) or set(raw) != {
        "schema_version",
        "checked_at",
        "projects",
    }:
        return None
    if raw.get("schema_version") != STATUS_SCHEMA_VERSION:
        return None
    checked_at = raw.get("checked_at")
    rows = raw.get("projects")
    if not isinstance(checked_at, (int, float)) or not isinstance(rows, list):
        return None
    statuses: list[ProjectSyncStatus] = []
    for row in rows:
        status = _status_from_json(row)
        if status is None:
            return None
        statuses.append(status)
    return SyncStatusSnapshot(float(checked_at), tuple(statuses))


def _write_agents_sync_status_snapshot(
    snapshot: SyncStatusSnapshot,
    *,
    path: Path | None = None,
) -> None:
    atomic_write_json(path or _status_snapshot_path(), snapshot.to_json_dict())


def rewrite_agents_sync_status_after_sync(
    projects: Sequence[str] = (),
    *,
    now: float | None = None,
    git_runner: GitRunner = run_git,
) -> SyncStatusSnapshot:
    """Rewrite the cache from post-sync local facts without fetching."""

    checked_at = time.time() if now is None else now
    selection = resolve_sync_targets(projects)
    statuses = [_status_from_outcome(outcome) for outcome in selection.outcomes]
    try:
        machine = require_machine_name()
    except (RuntimeError, ValueError) as exc:
        statuses.extend(
            ProjectSyncStatus(
                target.project_key,
                target.project,
                "configuration_error",
                error=f"machine identity is not configured: {exc}",
            )
            for target in selection.targets
        )
    else:
        previous = _read_agents_sync_status_snapshot()
        previous_by_key = (
            {status.project_key: status for status in previous.projects}
            if previous is not None
            else {}
        )
        for target in selection.targets:
            prior = previous_by_key.get(target.project_key)
            statuses.append(
                _revalidate_project_status(
                    target,
                    machine,
                    last_fetch_time=(prior.last_fetch_time if prior else None),
                    git_runner=git_runner,
                )
            )
    snapshot = SyncStatusSnapshot(
        checked_at,
        tuple(sorted(statuses, key=lambda item: item.project_key)),
    )
    _write_agents_sync_status_snapshot(snapshot)
    return snapshot


def _status_from_outcome(outcome: SyncOutcome) -> ProjectSyncStatus:
    state: StatusState
    if outcome.error:
        state = "error"
    elif outcome.skip_reason == "project is disabled" or (
        outcome.skip_reason and "disabled" in outcome.skip_reason
    ):
        state = "disabled"
    elif outcome.skip_reason:
        state = "not_created"
    else:
        state = "ready"
    return ProjectSyncStatus(
        outcome.project_key,
        outcome.project,
        state,
        detail=outcome.skip_reason,
        error=outcome.error,
    )


def _status_from_json(value: object) -> ProjectSyncStatus | None:
    if not isinstance(value, dict) or set(value) != {
        "project_key",
        "project",
        "state",
        "ahead",
        "behind",
        "unexported_agents",
        "last_fetch_time",
        "detail",
        "error",
    }:
        return None
    state = value.get("state")
    valid_states = {
        "ready",
        "disabled",
        "not_created",
        "missing_upstream",
        "configuration_error",
        "error",
    }
    if state not in valid_states:
        return None
    project_key = value.get("project_key")
    project = value.get("project")
    if not isinstance(project_key, str) or not isinstance(project, str):
        return None
    for key in ("ahead", "behind", "unexported_agents"):
        item = value.get(key)
        if item is not None and (type(item) is not int or item < 0):
            return None
    last_fetch = value.get("last_fetch_time")
    if last_fetch is not None and not isinstance(last_fetch, (int, float)):
        return None
    for key in ("detail", "error"):
        item = value.get(key)
        if item is not None and not isinstance(item, str):
            return None
    return ProjectSyncStatus(
        project_key,
        project,
        state,
        ahead=value.get("ahead"),
        behind=value.get("behind"),
        unexported_agents=value.get("unexported_agents"),
        last_fetch_time=float(last_fetch) if last_fetch is not None else None,
        detail=value.get("detail"),
        error=value.get("error"),
    )


def _snapshot_is_fresh(
    snapshot: SyncStatusSnapshot,
    *,
    now: float,
    ttl_seconds: float,
) -> bool:
    age = now - snapshot.checked_at
    return 0 <= age < ttl_seconds


__all__ = [
    "DEFAULT_STATUS_TTL_SECONDS",
    "get_agents_sync_status",
    "rewrite_agents_sync_status_after_sync",
]
