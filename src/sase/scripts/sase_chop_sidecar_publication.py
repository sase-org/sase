#!/usr/bin/env python3
"""Drain durable sidecar publication requests outside interactive commands."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
import json
import os
from pathlib import Path
import tempfile
import time

from sase.agents_sync.commit_publication import drain_agent_publications
from sase.agents_sync.models import ProjectTarget
from sase.agents_sync.publication_outbox import (
    AGENT_PUBLICATION_OUTBOX_FILENAME,
    PublicationKind,
    SidecarPublicationRequest,
    acknowledge_agent_publications,
    configured_publication_max_attempts,
    snapshot_agent_publications_from_path,
    update_agent_publications,
)
from sase.agents_sync.targets import resolve_sync_targets
from sase.bead_pages.publication import drain_bead_pages_publication
from sase.chops.builtin import BuiltinChopRuntime, builtin_chop, run_builtin_chop
from sase.chops.sdk import ChopResultBuilder
from sase.core.paths import sase_projects_dir
from sase.sdd._commit_store import drain_sidecar_push_publication
from sase.sdd.plan_header_refresh import drain_plan_header_publication
from sase.sdd.plan_refs import workspace_context_for_plan_resolution
from sase.sdd.store import resolve_sdd_store
from sase.sdd.store import SddStore

_RUN_EVERY_SECONDS = 30
_MAX_BACKOFF_SECONDS = 15 * 60
_BACKOFF_STATE_FILENAME = "sidecar_publication_backoff.json"
# Keep in sync with the ``publications`` lumberjack timeout in default_config.yml.
# The runner sends SIGKILL at this deadline, so the pass and every lock wait use
# smaller budgets and record backoff before beginning any project transaction.
_CHOP_TIMEOUT_SECONDS = 5 * 60.0
_WORK_BUDGET_SECONDS = 0.75 * _CHOP_TIMEOUT_SECONDS
_LOCK_WAIT_BUDGET_SECONDS = 0.5 * _CHOP_TIMEOUT_SECONDS
_MIN_LOCK_WAIT_SECONDS = 10.0


@dataclass(frozen=True)
class _BackoffEntry:
    failures: int
    next_attempt_at: datetime


@dataclass
class _DrainCounts:
    agents_published: int = 0
    bead_pages_published: int = 0
    plan_headers_refreshed: int = 0
    pushes_completed: int = 0
    requests_failed: int = 0
    requests_quarantined: int = 0

    def add(self, other: _DrainCounts) -> None:
        self.agents_published += other.agents_published
        self.bead_pages_published += other.bead_pages_published
        self.plan_headers_refreshed += other.plan_headers_refreshed
        self.pushes_completed += other.pushes_completed
        self.requests_failed += other.requests_failed
        self.requests_quarantined += other.requests_quarantined

    @property
    def completed(self) -> int:
        return (
            self.agents_published
            + self.bead_pages_published
            + self.plan_headers_refreshed
            + self.pushes_completed
        )


def _utc_now() -> datetime:
    return datetime.now(UTC)


def _parse_datetime(value: object) -> datetime | None:
    if not isinstance(value, str):
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def _read_backoff_state(path: Path) -> dict[str, _BackoffEntry]:
    try:
        with path.open(encoding="utf-8") as stream:
            payload = json.load(stream)
    except (json.JSONDecodeError, OSError):
        return {}
    if not isinstance(payload, dict):
        return {}

    state: dict[str, _BackoffEntry] = {}
    for project_key, raw_entry in payload.items():
        if not isinstance(project_key, str) or not isinstance(raw_entry, dict):
            continue
        failures = raw_entry.get("failures")
        next_attempt_at = _parse_datetime(raw_entry.get("next_attempt_at"))
        if (
            not isinstance(failures, int)
            or isinstance(failures, bool)
            or failures < 1
            or next_attempt_at is None
        ):
            continue
        state[project_key] = _BackoffEntry(failures, next_attempt_at)
    return state


def _write_backoff_state(path: Path, state: dict[str, _BackoffEntry]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        project_key: {
            "failures": entry.failures,
            "next_attempt_at": entry.next_attempt_at.isoformat(),
        }
        for project_key, entry in sorted(state.items())
    }
    fd, temporary_path = tempfile.mkstemp(
        dir=path.parent,
        prefix=f".{path.name}.",
        suffix=".tmp",
    )
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            json.dump(payload, stream, indent=2)
            stream.write("\n")
        os.replace(temporary_path, path)
    except BaseException:
        try:
            os.unlink(temporary_path)
        except OSError:
            pass
        raise


def _next_backoff_entry(
    previous: _BackoffEntry | None,
    *,
    now: datetime,
) -> _BackoffEntry:
    failures = (previous.failures if previous is not None else 0) + 1
    exponent = min(failures, 5)
    delay_seconds = min(
        _RUN_EVERY_SECONDS * (2**exponent),
        _MAX_BACKOFF_SECONDS,
    )
    return _BackoffEntry(
        failures=failures,
        next_attempt_at=now + timedelta(seconds=delay_seconds),
    )


def _project_lock_timeout(project_count: int) -> float:
    """Give every pending project a bounded share of the lock-wait budget."""

    return max(
        _MIN_LOCK_WAIT_SECONDS,
        _LOCK_WAIT_BUDGET_SECONDS / max(project_count, 1),
    )


def _persist_backoff_state(
    runtime: BuiltinChopRuntime,
    state_path: Path,
    state: dict[str, _BackoffEntry],
) -> None:
    try:
        _write_backoff_state(state_path, state)
    except Exception as exc:  # noqa: BLE001 - auxiliary state cannot fail the chop.
        runtime.log.warning(
            f"[sidecar_publication] Failed to persist publication backoff: {exc}"
        )


def _active_requests(
    items: tuple[SidecarPublicationRequest, ...],
) -> tuple[SidecarPublicationRequest, ...]:
    return tuple(item for item in items if not item.quarantined and not item.terminal)


def _snapshot_all_project(
    projects_root: Path,
    project_key: str,
) -> tuple[SidecarPublicationRequest, ...]:
    path = projects_root / project_key / AGENT_PUBLICATION_OUTBOX_FILENAME
    return snapshot_agent_publications_from_path(path, project_key)


def _snapshot_project(
    projects_root: Path,
    project_key: str,
) -> tuple[SidecarPublicationRequest, ...]:
    return _active_requests(_snapshot_all_project(projects_root, project_key))


def _projects_with_pending_publications(
    projects_root: Path,
    runtime: BuiltinChopRuntime,
) -> tuple[dict[str, tuple[SidecarPublicationRequest, ...]], int]:
    """Discover work through atomic, lock-free outbox snapshots."""

    pending: dict[str, tuple[SidecarPublicationRequest, ...]] = {}
    failed = 0
    try:
        project_dirs = sorted(
            (path for path in projects_root.iterdir() if path.is_dir()),
            key=lambda path: path.name,
        )
    except OSError as exc:
        runtime.log.warning(
            f"[sidecar_publication] Could not scan project queues: {exc}"
        )
        return {}, 1

    for project_dir in project_dirs:
        path = project_dir / AGENT_PUBLICATION_OUTBOX_FILENAME
        if not path.is_file():
            continue
        try:
            requests = _active_requests(
                snapshot_agent_publications_from_path(path, project_dir.name)
            )
        except Exception as exc:  # noqa: BLE001 - isolate corrupt project queues.
            failed += 1
            runtime.log.warning(
                f"[sidecar_publication] Could not read queue for "
                f"{project_dir.name}: {exc}"
            )
            continue
        if requests:
            pending[project_dir.name] = requests
    return pending, failed


def _resolve_project_target(project_key: str) -> ProjectTarget:
    selection = resolve_sync_targets((project_key,))
    if len(selection.targets) == 1:
        return selection.targets[0]
    outcome = selection.outcomes[0] if selection.outcomes else None
    detail = (
        (outcome.error or outcome.skip_reason) if outcome is not None else None
    ) or "project publication target is unavailable"
    raise RuntimeError(detail)


def _record_request_failure(
    project_key: str,
    request: SidecarPublicationRequest,
    error: str,
) -> bool:
    """Record one failed attempt and report a new quarantine transition."""

    updated = update_agent_publications(
        project_key,
        (request.logical_key,),
        error=error,
        increment_attempts=True,
        quarantine_threshold=configured_publication_max_attempts(),
    )
    current = next(
        (item for item in updated if item.logical_key == request.logical_key),
        None,
    )
    return bool(
        current is not None
        and current.quarantined
        and not current.terminal
        and not request.quarantined
    )


def _record_project_failure(
    project_key: str,
    requests: tuple[SidecarPublicationRequest, ...],
    error: str,
) -> _DrainCounts:
    counts = _DrainCounts(requests_failed=len(requests))
    for request in requests:
        if _record_request_failure(project_key, request, error):
            counts.requests_quarantined += 1
    return counts


def _resolve_sdd_store(target: ProjectTarget) -> SddStore:
    workspace_dir, workspace_num = workspace_context_for_plan_resolution(
        target.primary_checkout
    )
    return resolve_sdd_store(workspace_dir, workspace_num)


def _drain_non_agent_request(
    request: SidecarPublicationRequest,
    target: ProjectTarget,
    *,
    lock_timeout: float,
) -> None:
    if request.kind == "bead_pages":
        bead_outcome = drain_bead_pages_publication(
            request,
            primary_root=target.primary_checkout,
            project=target.project,
            lock_timeout_seconds=lock_timeout,
        )
        if bead_outcome.error:
            raise RuntimeError(bead_outcome.error)
        return
    if request.kind == "plan_header":
        plan_outcome = drain_plan_header_publication(
            request,
            primary_root=target.primary_checkout,
            project=target.project,
            lock_timeout_seconds=lock_timeout,
        )
        if plan_outcome.error:
            raise RuntimeError(plan_outcome.error)
        return
    if request.kind == "sidecar_push":
        drain_sidecar_push_publication(
            request,
            _resolve_sdd_store(target),
            lock_timeout_seconds=lock_timeout,
        )
        return
    raise ValueError(f"unsupported publication request kind: {request.kind}")


def _increment_success(counts: _DrainCounts, kind: PublicationKind) -> None:
    if kind == "bead_pages":
        counts.bead_pages_published += 1
    elif kind == "plan_header":
        counts.plan_headers_refreshed += 1
    elif kind == "sidecar_push":
        counts.pushes_completed += 1


def _drain_project(
    projects_root: Path,
    project_key: str,
    *,
    lock_timeout: float,
) -> tuple[_DrainCounts, bool]:
    """Drain one project in dependency order; return counts and success."""

    counts = _DrainCounts()
    initial = _snapshot_project(projects_root, project_key)
    try:
        target = _resolve_project_target(project_key)
    except Exception as exc:  # noqa: BLE001 - isolate one unavailable project.
        error = str(exc) or type(exc).__name__
        return _record_project_failure(project_key, initial, error), False

    agent_requests = tuple(item for item in initial if item.kind == "agent_hood")
    if agent_requests:
        before = {item.logical_key: item for item in agent_requests}
        outcome = drain_agent_publications(
            project_key,
            lock_timeout_seconds=lock_timeout,
        )
        counts.agents_published += outcome.drained
        if outcome.error or outcome.skip_reason:
            error = outcome.error or outcome.skip_reason or "agent publication failed"
            remaining = _snapshot_all_project(projects_root, project_key)
            for request in remaining:
                previous = before.get(request.logical_key)
                if previous is None or request.kind != "agent_hood":
                    continue
                counts.requests_failed += 1
                if request.quarantined and not previous.quarantined:
                    counts.requests_quarantined += 1
                    continue
                # The agent drainer normally records its own failure. Fill in
                # failures that occurred before it reached the queue mutation,
                # and apply the chop's quarantine threshold without double
                # incrementing an already-recorded attempt.
                if request.attempts == previous.attempts:
                    if _record_request_failure(project_key, request, error):
                        counts.requests_quarantined += 1
                elif not request.quarantined:
                    updated = update_agent_publications(
                        project_key,
                        (request.logical_key,),
                        error=error,
                        quarantine_threshold=configured_publication_max_attempts(),
                    )
                    current = next(
                        (
                            item
                            for item in updated
                            if item.logical_key == request.logical_key
                        ),
                        None,
                    )
                    if current is not None and current.quarantined:
                        counts.requests_quarantined += 1
            return counts, False

    # Reload after every acknowledgment. A successful bead or plan drain may
    # enqueue its sidecar push, which must be observed and handled last in the
    # same tick rather than being hidden by the initial snapshot.
    while True:
        pending = tuple(
            item
            for item in _snapshot_project(projects_root, project_key)
            if item.kind != "agent_hood"
        )
        if not pending:
            return counts, True
        request = min(
            pending,
            key=lambda item: (item.ordering_rank, item.created_at, item.id),
        )
        try:
            _drain_non_agent_request(request, target, lock_timeout=lock_timeout)
        except Exception as exc:  # noqa: BLE001 - one project cannot stop the pass.
            error = str(exc) or type(exc).__name__
            counts.requests_failed += 1
            if _record_request_failure(project_key, request, error):
                counts.requests_quarantined += 1
            return counts, False
        acknowledge_agent_publications(project_key, (request.logical_key,))
        _increment_success(counts, request.kind)


def _summary(
    runtime: BuiltinChopRuntime,
    *,
    projects_pending: int,
    counts: _DrainCounts,
    projects_backed_off: int = 0,
    projects_deferred: int = 0,
    reason: str | None = None,
) -> ChopResultBuilder:
    return runtime.emit_summary(
        {
            "projects_pending": projects_pending,
            "agents_published": counts.agents_published,
            "bead_pages_published": counts.bead_pages_published,
            "plan_headers_refreshed": counts.plan_headers_refreshed,
            "pushes_completed": counts.pushes_completed,
            "requests_failed": counts.requests_failed,
            "requests_quarantined": counts.requests_quarantined,
            "projects_backed_off": projects_backed_off,
            "projects_deferred": projects_deferred,
        },
        reason=reason,
    )


@builtin_chop("sidecar_publication")
def _run(runtime: BuiltinChopRuntime) -> ChopResultBuilder:
    projects_root = sase_projects_dir()
    pending, discovery_failures = _projects_with_pending_publications(
        projects_root, runtime
    )
    counts = _DrainCounts(requests_failed=discovery_failures)
    now = _utc_now()
    state_path = Path(runtime.context.state_dir) / _BACKOFF_STATE_FILENAME
    backoff_state = _read_backoff_state(state_path)

    stale_projects = [key for key in backoff_state if key not in pending]
    for project_key in stale_projects:
        del backoff_state[project_key]
    if stale_projects:
        _persist_backoff_state(runtime, state_path, backoff_state)

    if not pending:
        reason = "queue_scan_failed" if discovery_failures else "no_pending_requests"
        return _summary(
            runtime,
            projects_pending=0,
            counts=counts,
            reason=reason,
        )

    lock_timeout = _project_lock_timeout(len(pending))
    work_deadline = time.monotonic() + _WORK_BUDGET_SECONDS
    projects_backed_off = 0
    projects_deferred = 0
    projects_failed = 0

    for project_key in sorted(pending):
        entry = backoff_state.get(project_key)
        if entry is not None and now < entry.next_attempt_at:
            projects_backed_off += 1
            continue
        if time.monotonic() >= work_deadline:
            projects_deferred += 1
            continue

        # Persist pessimistically before the attempt. If the axe timeout kills
        # this process, the next tick backs off instead of attacking the same
        # slow lock or network operation immediately.
        backoff_state[project_key] = _next_backoff_entry(entry, now=now)
        _persist_backoff_state(runtime, state_path, backoff_state)

        project_counts, succeeded = _drain_project(
            projects_root,
            project_key,
            lock_timeout=lock_timeout,
        )
        counts.add(project_counts)
        if succeeded:
            del backoff_state[project_key]
            _persist_backoff_state(runtime, state_path, backoff_state)
        else:
            projects_failed += 1

    summary_reason: str | None = None
    if counts.completed == 0:
        if projects_failed or counts.requests_failed:
            summary_reason = "publication_failed"
        elif projects_backed_off:
            summary_reason = "all_backed_off"
        elif projects_deferred:
            summary_reason = "budget_exhausted"

    return _summary(
        runtime,
        projects_pending=len(pending),
        counts=counts,
        projects_backed_off=projects_backed_off,
        projects_deferred=projects_deferred,
        reason=summary_reason,
    )


def main() -> None:
    run_builtin_chop("sidecar_publication")


if __name__ == "__main__":
    main()
