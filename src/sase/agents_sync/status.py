"""Atomic status snapshots with explicit-fetch and cached-only modes."""

from __future__ import annotations

from collections.abc import Sequence
import json
import math
from pathlib import Path
import re
import time

from sase.agents_sync.bundles import (  # noqa: F401 - compatibility patch seam
    count_unexported_local_agents,
)
from sase.agents_sync.git import GitRunner, run_git
from sase.agents_sync.git_objects import LocalGitObjectReader
from sase.agents_sync.incoming_cache import (
    captured_incoming_hood_from_json,
    reconcile_pending_items,
)
from sase.agents_sync.incoming_detection import capture_fetched_agent_updates
from sase.agents_sync.io import AgentsSyncFormatError, atomic_write_json, read_manifest
from sase.agents_sync.models import (
    STATUS_SCHEMA_VERSION,
    CapturedIncomingHood,
    ProjectSyncStatus,
    ProjectTarget,
    StatusState,
    SyncOutcome,
    SyncStatusSnapshot,
)
from sase.agents_sync.publication_outbox import (
    publication_quarantine_diagnostics,
)
from sase.agents_sync.targets import resolve_sync_targets
from sase.config import require_agent_owner_identity
from sase.core.agent_identity_facade import AgentOwnerIdentity
from sase.core.paths import sase_home

DEFAULT_STATUS_TTL_SECONDS = 10 * 60
_SHA_RE = re.compile(r"^(?:[0-9a-f]{40}|[0-9a-f]{64})$")


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
    lock_timeout_seconds: float | None = None,
) -> SyncStatusSnapshot:
    """Return status from cache, fetching only when explicitly requested.

    Plain checks and ``revalidate_only`` both resolve local target
    configuration and reconcile persisted immutable items against metadata and
    receipts. They never run Git, enumerate sidecar manifests, scan local
    artifacts, or mutate the sidecar checkout. ``refresh=True`` is the sole
    network-producing mode.
    """

    if refresh and revalidate_only:
        raise ValueError("refresh and revalidate_only are mutually exclusive")
    del ttl_seconds  # Retained for public compatibility; age no longer implies fetch.

    checked_at = time.time() if now is None else now
    if not math.isfinite(checked_at) or checked_at < 0:
        raise ValueError("now must be a finite non-negative timestamp")
    selection = resolve_sync_targets(projects)
    previous = _read_agents_sync_status_snapshot(path=path)
    previous_by_key = (
        {status.project_key: status for status in previous.projects}
        if previous is not None
        else {}
    )
    statuses = [_status_from_outcome(outcome) for outcome in selection.outcomes]
    try:
        owner = require_agent_owner_identity()
    except (RuntimeError, ValueError) as exc:
        statuses.extend(
            ProjectSyncStatus(
                target.project_key,
                target.project,
                "configuration_error",
                error=f"owner identity is not configured: {exc}",
            )
            for target in selection.targets
        )
    else:
        for target in selection.targets:
            prior = previous_by_key.get(target.project_key)
            if refresh:
                statuses.append(
                    _refresh_project_status(
                        target,
                        owner,
                        prior=prior,
                        checked_at=checked_at,
                        git_runner=git_runner,
                        lock_timeout_seconds=lock_timeout_seconds,
                    )
                )
            else:
                statuses.append(_reconcile_project_status(target, prior))

    snapshot = SyncStatusSnapshot(
        checked_at,
        tuple(sorted(statuses, key=lambda item: item.project_key)),
    )
    _write_agents_sync_status_snapshot(snapshot, path=path)
    return snapshot


def _refresh_project_status(
    target: ProjectTarget,
    owner: AgentOwnerIdentity,
    *,
    prior: ProjectSyncStatus | None,
    checked_at: float,
    git_runner: GitRunner,
    lock_timeout_seconds: float | None,
) -> ProjectSyncStatus:
    repo = target.sidecar_path
    if not (repo / ".git").exists():
        return _reconcile_project_status(target, prior)

    from sase.agents_sync import git_sync

    timeout = (
        git_sync.configured_agents_lock_timeout()
        if lock_timeout_seconds is None
        else max(lock_timeout_seconds, 0.0)
    )
    lock_path = (
        git_sync.agents_git_dir(target.sidecar_path, git_runner)
        / "sase-agents-sync.lock"
    )
    with git_sync.bounded_agents_lock(lock_path, timeout) as acquired:
        if not acquired:
            return _status_error(
                _reconcile_project_status(target, prior),
                "agents sync lock is busy; retry the refresh",
            )
        fetched = git_runner(
            repo,
            ["fetch", "--prune", "origin"],
            network=True,
            op="agents_sync.status_fetch",
        )
        if fetched.returncode != 0:
            detail = (fetched.stderr or fetched.stdout or "unknown git error").strip()
            return _status_error(
                _reconcile_project_status(target, prior),
                f"git fetch failed: {detail}",
            )
        try:
            report = capture_fetched_agent_updates(
                target,
                owner,
                reader=LocalGitObjectReader(repo, git_runner=git_runner),
                previous_items=prior.pending_updates if prior is not None else (),
                now=checked_at,
            )
        except (AgentsSyncFormatError, OSError, RuntimeError, ValueError) as exc:
            return _status_error(
                _reconcile_project_status(target, prior),
                f"could not inspect fetched agents commit: {exc}",
                last_fetch_time=checked_at,
            )
        diagnostics = _revalidate_project_diagnostics(
            target,
            owner.machine_name,
            last_fetch_time=checked_at,
            git_runner=git_runner,
        )
        return ProjectSyncStatus(
            target.project_key,
            target.project,
            diagnostics.state,
            ahead=diagnostics.ahead,
            behind=diagnostics.behind,
            unexported_agents=diagnostics.unexported_agents,
            last_fetch_time=checked_at,
            detail=diagnostics.detail,
            error=diagnostics.error,
            fetched_ref=report.fetched.ref,
            fetched_sha=report.fetched.sha,
            pending_updates=report.pending_updates,
            validated_foreign_count=report.validated_foreign_count,
            exact_owner_count=report.exact_owner_count,
            quarantine_diagnostics=(
                *report.diagnostics,
                *_publication_diagnostics(target.project_key),
            ),
            cache_updated_at=report.cache_updated_at,
        )


def _reconcile_project_status(
    target: ProjectTarget,
    prior: ProjectSyncStatus | None,
) -> ProjectSyncStatus:
    """Reconcile metadata and receipts without Git or artifact discovery."""

    previous_items = prior.pending_updates if prior is not None else ()
    pending, diagnostics = reconcile_pending_items(
        previous_items,
        project_key=target.project_key,
    )
    quarantines = tuple(
        dict.fromkeys(
            (
                *(
                    diagnostic
                    for diagnostic in (
                        prior.quarantine_diagnostics if prior is not None else ()
                    )
                    if not diagnostic.startswith("publication request ")
                ),
                *diagnostics,
                *_publication_diagnostics(target.project_key),
            )
        )
    )
    if not (target.sidecar_path / ".git").exists():
        state: StatusState = "not_created"
        detail: str | None = "agents sidecar clone does not exist on this machine"
    elif prior is None:
        state = "ready"
        detail = "cached diagnostics unavailable; run with --refresh to update"
    else:
        state = prior.state
        detail = prior.detail
    return ProjectSyncStatus(
        target.project_key,
        target.project,
        state,
        ahead=prior.ahead if prior is not None else None,
        behind=prior.behind if prior is not None else None,
        unexported_agents=(prior.unexported_agents if prior is not None else None),
        last_fetch_time=prior.last_fetch_time if prior is not None else None,
        detail=detail,
        error=prior.error if prior is not None else None,
        fetched_ref=prior.fetched_ref if prior is not None else None,
        fetched_sha=prior.fetched_sha if prior is not None else None,
        pending_updates=pending,
        validated_foreign_count=(
            prior.validated_foreign_count if prior is not None else 0
        ),
        exact_owner_count=prior.exact_owner_count if prior is not None else 0,
        quarantine_diagnostics=quarantines,
        cache_updated_at=prior.cache_updated_at if prior is not None else None,
    )


def _publication_diagnostics(project_key: str) -> tuple[str, ...]:
    try:
        return publication_quarantine_diagnostics(project_key)
    except (OSError, RuntimeError, ValueError) as exc:
        return (f"publication outbox diagnostics unavailable: {exc}",)


def _revalidate_project_diagnostics(
    target: ProjectTarget,
    machine: str,
    *,
    last_fetch_time: float | None,
    git_runner: GitRunner = run_git,
) -> ProjectSyncStatus:
    """Refresh backward-compatible worktree diagnostics after explicit fetch."""

    repo = target.sidecar_path
    if not (repo / ".git").exists():
        return ProjectSyncStatus(
            target.project_key,
            target.project,
            "not_created",
            last_fetch_time=last_fetch_time,
            detail="agents sidecar clone does not exist on this machine",
        )
    legacy_manifest_path = repo / "manifest.json"
    manifest = None
    if legacy_manifest_path.is_file():
        try:
            manifest = read_manifest(legacy_manifest_path)
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
            unexported_agents=(
                count_unexported_local_agents(
                    target, manifest, machine, git_runner=git_runner
                )
                if manifest is not None
                else 0
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
        unexported = (
            count_unexported_local_agents(
                target, manifest, machine, git_runner=git_runner
            )
            if manifest is not None
            else 0
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


# Compatibility for callers/tests that used the former local-diagnostics seam.
_revalidate_project_status = _revalidate_project_diagnostics


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
    checked_at = _finite_json_time(raw.get("checked_at"))
    rows = raw.get("projects")
    if checked_at is None or not isinstance(rows, list):
        return None
    statuses: list[ProjectSyncStatus] = []
    for row in rows:
        status = _status_from_json(row)
        if status is None:
            return None
        statuses.append(status)
    if len({status.project_key for status in statuses}) != len(statuses):
        return None
    return SyncStatusSnapshot(checked_at, tuple(statuses))


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
    """Rewrite status from cache and receipts without network or sidecar scans."""

    del git_runner  # Compatibility argument; cached projection never runs Git.
    return get_agents_sync_status(
        projects,
        revalidate_only=True,
        now=now,
    )


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
    keys = {
        "project_key",
        "project",
        "state",
        "ahead",
        "behind",
        "unexported_agents",
        "last_fetch_time",
        "detail",
        "error",
        "fetched_ref",
        "fetched_sha",
        "pending_updates",
        "validated_foreign_count",
        "exact_owner_count",
        "quarantine_diagnostics",
        "cache_updated_at",
    }
    if not isinstance(value, dict) or set(value) != keys:
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
    if (
        not isinstance(project_key, str)
        or not _valid_component(project_key)
        or (not isinstance(project, str) or not project or "\x00" in project)
    ):
        return None
    counts: dict[str, int | None] = {}
    for key in ("ahead", "behind", "unexported_agents"):
        item = value.get(key)
        if item is not None and (type(item) is not int or item < 0):
            return None
        counts[key] = item
    observation_counts: dict[str, int] = {}
    for key in ("validated_foreign_count", "exact_owner_count"):
        item = value.get(key)
        if type(item) is not int or item < 0:
            return None
        observation_counts[key] = item
    last_fetch = value.get("last_fetch_time")
    cache_updated = value.get("cache_updated_at")
    if last_fetch is not None and _finite_json_time(last_fetch) is None:
        return None
    if cache_updated is not None and _finite_json_time(cache_updated) is None:
        return None
    for key in ("detail", "error"):
        item = value.get(key)
        if item is not None and not isinstance(item, str):
            return None
    fetched_ref = value.get("fetched_ref")
    fetched_sha = value.get("fetched_sha")
    if fetched_ref is not None and not _valid_fetched_ref(fetched_ref):
        return None
    if fetched_sha is not None and (
        not isinstance(fetched_sha, str) or _SHA_RE.fullmatch(fetched_sha) is None
    ):
        return None
    if (fetched_ref is None) != (fetched_sha is None):
        return None
    raw_pending = value.get("pending_updates")
    if not isinstance(raw_pending, list):
        return None
    pending: list[CapturedIncomingHood] = []
    try:
        pending.extend(captured_incoming_hood_from_json(item) for item in raw_pending)
    except AgentsSyncFormatError:
        return None
    if any(
        item.project_key != project_key or item.project != project for item in pending
    ):
        return None
    raw_diagnostics = value.get("quarantine_diagnostics")
    if not isinstance(raw_diagnostics, list) or not all(
        isinstance(item, str) for item in raw_diagnostics
    ):
        return None
    return ProjectSyncStatus(
        project_key,
        project,
        state,  # type: ignore[arg-type]
        ahead=counts["ahead"],
        behind=counts["behind"],
        unexported_agents=counts["unexported_agents"],
        last_fetch_time=(
            _finite_json_time(last_fetch) if last_fetch is not None else None
        ),
        detail=value.get("detail"),
        error=value.get("error"),
        fetched_ref=fetched_ref,
        fetched_sha=fetched_sha,
        pending_updates=tuple(pending),
        validated_foreign_count=observation_counts["validated_foreign_count"],
        exact_owner_count=observation_counts["exact_owner_count"],
        quarantine_diagnostics=tuple(raw_diagnostics),
        cache_updated_at=(
            _finite_json_time(cache_updated) if cache_updated is not None else None
        ),
    )


def _status_error(
    status: ProjectSyncStatus,
    error: str,
    *,
    last_fetch_time: float | None = None,
) -> ProjectSyncStatus:
    return ProjectSyncStatus(
        status.project_key,
        status.project,
        "error",
        ahead=status.ahead,
        behind=status.behind,
        unexported_agents=status.unexported_agents,
        last_fetch_time=(
            status.last_fetch_time if last_fetch_time is None else last_fetch_time
        ),
        detail=status.detail,
        error=error,
        fetched_ref=status.fetched_ref,
        fetched_sha=status.fetched_sha,
        pending_updates=status.pending_updates,
        validated_foreign_count=status.validated_foreign_count,
        exact_owner_count=status.exact_owner_count,
        quarantine_diagnostics=status.quarantine_diagnostics,
        cache_updated_at=status.cache_updated_at,
    )


def _finite_json_time(value: object) -> float | None:
    if (
        isinstance(value, bool)
        or not isinstance(value, (int, float))
        or not math.isfinite(value)
        or value < 0
    ):
        return None
    return float(value)


def _valid_component(value: object) -> bool:
    return (
        isinstance(value, str)
        and bool(value)
        and value not in {".", ".."}
        and not value.startswith(".")
        and "/" not in value
        and "\\" not in value
        and "\x00" not in value
        and len(value.encode("utf-8")) <= 255
    )


def _valid_fetched_ref(value: object) -> bool:
    return value == "HEAD" or (
        isinstance(value, str)
        and value.startswith("refs/remotes/")
        and len(value.encode("utf-8")) <= 1024
        and not any(ord(char) <= 32 or char in "~^:?*[\\" for char in value)
        and ".." not in value
        and not value.endswith((".", "/"))
    )


__all__ = [
    "DEFAULT_STATUS_TTL_SECONDS",
    "get_agents_sync_status",
    "rewrite_agents_sync_status_after_sync",
]
