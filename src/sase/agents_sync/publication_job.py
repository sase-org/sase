"""Bounded host-owned drains for durable agent publication requests."""

from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass, field
import fcntl
import os
from pathlib import Path
import time
from collections.abc import Iterator
from typing import Any

from sase.agents_sync._commit_publication_outbox import active_agent_publications
from sase.agents_sync._commit_publication_types import CommitPublicationOutcome
from sase.agents_sync.git import GitRunner, run_git
from sase.agents_sync.publication_doorbell import (
    PublicationHintClaim,
    claim_publication_hints,
    finish_hint_claim,
    ring_publication_doorbell,
    write_publication_heartbeat,
)
from sase.agents_sync.publication_outbox import AgentPublicationOutboxItem
from sase.agents_sync.referenced_by_outbox import list_referenced_by_requests
from sase.agents_sync.models import ProjectTarget
from sase.agents_sync.targets import resolve_sync_targets
from sase.core.paths import sase_home, sase_projects_dir
from sase.core.project_lifecycle_facade import list_project_records
from sase.sdd.artifact_link_outbox import drain_artifact_link_outbox
from sase.sdd.artifact_link_store import resolve_machine_artifact_link_store

PUBLICATION_JOB_WORK_BUDGET_SECONDS = 240.0
_DONE_MARKER_GRACE_SECONDS = 10 * 60
_HOOD_BATCH_LIMIT = 25
_LOCK_BUSY_TEXT = "agents sync lock is busy"


@dataclass(slots=True)
class _PublicationJobSummary:
    """Counters and per-project heartbeat state from one scheduler pass."""

    projects: int = 0
    hood_drained: int = 0
    link_drained: int = 0
    referenced_by_drained: int = 0
    active_remaining: int = 0
    lock_busy: int = 0
    deferred_projects: int = 0
    errors: int = 0
    skipped_overlap: bool = False
    diagnostics: list[str] = field(default_factory=list)
    project_stats: dict[str, dict[str, object]] = field(default_factory=dict)


@dataclass(slots=True)
class _ProjectPass:
    hood_drained: int = 0
    link_drained: int = 0
    referenced_by_drained: int = 0
    lock_busy: bool = False
    deferred: bool = False
    error: str | None = None
    preserve_hints: bool = False
    outcome: str = "idle"


def run_publication_job(
    *,
    git_runner: GitRunner = run_git,
    work_budget_seconds: float = PUBLICATION_JOB_WORK_BUDGET_SECONDS,
) -> _PublicationJobSummary:
    """Drain enabled projects, then write the publisher heartbeat."""

    with _publisher_job_lock() as acquired:
        if not acquired:
            return _PublicationJobSummary(skipped_overlap=True)
        return _run_publication_job(
            git_runner=git_runner,
            work_budget_seconds=work_budget_seconds,
        )


def _run_publication_job(
    *,
    git_runner: GitRunner,
    work_budget_seconds: float,
) -> _PublicationJobSummary:
    """Execute one pass while the process-wide publisher lock is held."""

    summary = _PublicationJobSummary()
    started = time.monotonic()
    deadline = started + max(0.0, work_budget_seconds)
    try:
        records = list_project_records(
            sase_projects_dir(),
            include_states=("enabled",),
            include_home=False,
            projects_only=True,
        )
        project_keys = tuple(
            sorted(
                {
                    record.project_name
                    for record in records
                    if record.is_project and record.workspace_dir
                }
            )
        )
    except Exception as exc:  # noqa: BLE001 - heartbeat exposes failed discovery.
        summary.errors += 1
        summary.diagnostics.append(f"could not list enabled projects: {exc}")
        project_keys = ()
    targets: dict[str, ProjectTarget] = {}
    if project_keys:
        try:
            selection = resolve_sync_targets(project_keys)
            targets = {target.project_key: target for target in selection.targets}
            for outcome in selection.outcomes:
                if outcome.error:
                    summary.errors += 1
                    summary.diagnostics.append(
                        f"{outcome.project_key}: {outcome.error}"
                    )
        except Exception as exc:  # noqa: BLE001 - projects are retried next tick.
            summary.errors += 1
            summary.diagnostics.append(f"could not resolve publication targets: {exc}")

    summary.projects = len(project_keys)
    for index, project_key in enumerate(project_keys):
        if time.monotonic() >= deadline:
            summary.deferred_projects += len(project_keys) - index
            for deferred_key in project_keys[index:]:
                summary.project_stats[deferred_key] = {
                    "active_count": _safe_active_count(deferred_key),
                    "oldest_active_age_seconds": _oldest_active_age(deferred_key),
                    "last_outcome": "deferred_budget",
                }
                _safe_ring(deferred_key)
            break
        target = targets.get(project_key)
        if target is None:
            summary.errors += 1
            summary.diagnostics.append(
                f"{project_key}: no usable agents publication target"
            )
            _safe_ring(project_key)
            summary.project_stats[project_key] = {
                "active_count": _safe_active_count(project_key),
                "oldest_active_age_seconds": _oldest_active_age(project_key),
                "last_outcome": "target_unavailable",
            }
            continue
        try:
            result = _drain_project(
                target,
                deadline=deadline,
                git_runner=git_runner,
            )
        except Exception as exc:  # noqa: BLE001 - one project cannot starve others.
            result = _ProjectPass(error=str(exc) or type(exc).__name__, outcome="error")
            result.preserve_hints = True
            summary.diagnostics.append(f"{project_key}: {result.error}")
            _safe_ring(project_key)
        summary.hood_drained += result.hood_drained
        summary.link_drained += result.link_drained
        summary.referenced_by_drained += result.referenced_by_drained
        summary.lock_busy += int(result.lock_busy)
        summary.deferred_projects += int(result.deferred)
        if result.error:
            summary.errors += 1
            summary.diagnostics.append(f"{project_key}: {result.error}")
        active = _safe_active_items(project_key)
        active_count = len(active)
        summary.active_remaining += active_count
        publishable_count = sum(_publication_is_ready(item) for item in active)
        refby_count = _safe_referenced_by_count(project_key)
        if (
            publishable_count
            or refby_count
            or result.lock_busy
            or result.deferred
            or result.preserve_hints
        ):
            _safe_ring(project_key)
        summary.project_stats[project_key] = {
            "active_count": active_count,
            "oldest_active_age_seconds": _oldest_age(active),
            "last_outcome": result.outcome,
        }

    try:
        write_publication_heartbeat(summary.project_stats)
    except Exception as exc:  # noqa: BLE001 - the next pass retries heartbeat.
        summary.errors += 1
        summary.diagnostics.append(f"could not write publisher heartbeat: {exc}")
    return summary


@contextmanager
def _publisher_job_lock() -> Iterator[bool]:
    """Exclude overlapping scheduler invocations; SIGKILL releases this flock."""

    lock_path = sase_home() / "agent_publication" / "publisher.lock"
    lock_path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    fd = os.open(lock_path, os.O_CREAT | os.O_RDWR, 0o600)
    acquired = False
    try:
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            acquired = True
        except BlockingIOError:
            pass
        yield acquired
    finally:
        if acquired:
            fcntl.flock(fd, fcntl.LOCK_UN)
        os.close(fd)


def _drain_project(
    target: ProjectTarget,
    *,
    deadline: float,
    git_runner: GitRunner,
) -> _ProjectPass:
    from sase.agents_sync._commit_publication_queue import (
        drain_selected_agent_publications,
    )
    from sase.agents_sync.referenced_by_events import legacy_referenced_by_writes_fenced
    from sase.agents_sync.referenced_by_publication import drain_referenced_by_requests

    project_key = target.project_key
    claim = claim_publication_hints(project_key)
    result = _ProjectPass()
    try:
        active = active_agent_publications(project_key)
        active_by_key = {
            item.logical_key: item for item in active if _publication_is_ready(item)
        }
        hinted_keys = _hinted_keys(claim, active_by_key)
        attempted: set[tuple[str, str]] = set()

        while hinted_keys and time.monotonic() < deadline:
            batch = tuple(key for key in hinted_keys if key not in attempted)[
                :_HOOD_BATCH_LIMIT
            ]
            if not batch:
                break
            before = active_agent_publications(project_key)
            outcome = drain_selected_agent_publications(
                project_key,
                batch,
                git_runner=git_runner,
            )
            result.hood_drained += outcome.drained
            attempted.update(batch)
            after = active_agent_publications(project_key)
            if _is_lock_busy(outcome):
                result.lock_busy = True
                result.preserve_hints = True
                result.outcome = "lock_busy"
                break
            if outcome.error or outcome.skip_reason:
                result.error = outcome.error or outcome.skip_reason
                result.preserve_hints = bool(
                    set(batch) & {item.logical_key for item in after}
                )
                result.outcome = "hood_error"
                break
            if not _made_progress(before, after, outcome):
                result.outcome = "hood_no_progress"
                break
            active_by_key = {
                item.logical_key: item for item in after if _publication_is_ready(item)
            }
            hinted_keys = tuple(key for key in hinted_keys if key in active_by_key)

        if not result.lock_busy and result.error is None:
            while time.monotonic() < deadline:
                before = tuple(
                    item
                    for item in active_agent_publications(project_key)
                    if _publication_is_ready(item)
                )
                if not before:
                    break
                batch = tuple(item.logical_key for item in before[:_HOOD_BATCH_LIMIT])
                outcome = drain_selected_agent_publications(
                    project_key,
                    batch,
                    git_runner=git_runner,
                )
                result.hood_drained += outcome.drained
                after = tuple(
                    item
                    for item in active_agent_publications(project_key)
                    if _publication_is_ready(item)
                )
                if _is_lock_busy(outcome):
                    result.lock_busy = True
                    result.preserve_hints = bool(
                        set(batch) & {item.logical_key for item in after}
                    )
                    result.outcome = "lock_busy"
                    break
                if outcome.error or outcome.skip_reason:
                    result.error = outcome.error or outcome.skip_reason
                    result.preserve_hints = bool(
                        set(batch) & {item.logical_key for item in after}
                    )
                    result.outcome = "hood_error"
                    break
                if not _made_progress(before, after, outcome):
                    result.outcome = "hood_no_progress"
                    break
            if time.monotonic() >= deadline and any(
                _publication_is_ready(item)
                for item in active_agent_publications(project_key)
            ):
                result.deferred = True
                result.preserve_hints = result.preserve_hints or bool(hinted_keys)
                result.outcome = "deferred_budget"

        if time.monotonic() >= deadline:
            result.deferred = True
            result.preserve_hints = result.preserve_hints or bool(claim.hints)
            if result.outcome == "idle":
                result.outcome = "deferred_budget"

        link_agents = _hinted_link_agents(claim)
        if link_agents and time.monotonic() < deadline:
            try:
                store = resolve_machine_artifact_link_store(
                    project_key,
                    target.primary_checkout,
                    deadline=deadline,
                )
                link_report = drain_artifact_link_outbox(
                    store=store,
                    agent_names=link_agents,
                    drop_stale_terminal=False,
                    deadline=deadline,
                )
                result.link_drained += link_report.drained
                if link_report.selected_retained:
                    result.preserve_hints = True
                    result.outcome = "link_pending"
                elif link_report.deferred:
                    result.preserve_hints = True
                    result.deferred = True
                    result.outcome = "deferred_budget"
            except Exception as exc:  # noqa: BLE001 - hints retry on next pass.
                result.error = f"artifact-link drain failed: {exc}"
                result.preserve_hints = True
                result.outcome = "link_error"
        elif link_agents:
            result.preserve_hints = True
            result.deferred = True
            result.outcome = "deferred_budget"

        pending_refby = _safe_referenced_by_items(project_key)
        if pending_refby and time.monotonic() < deadline:
            try:
                if not legacy_referenced_by_writes_fenced(target):
                    before_count = len(pending_refby)
                    diagnostics = drain_referenced_by_requests(
                        target,
                        git_runner=git_runner,
                    )
                    after_count = len(_safe_referenced_by_items(project_key))
                    result.referenced_by_drained += max(0, before_count - after_count)
                    if diagnostics:
                        result.error = "; ".join(diagnostics)
                        if result.outcome == "idle":
                            result.outcome = "referenced_by_error"
            except Exception as exc:  # noqa: BLE001 - retry on the next tick.
                result.error = f"referenced-by drain failed: {exc}"
                if result.outcome == "idle":
                    result.outcome = "referenced_by_error"

        pending_active = active_agent_publications(project_key)
        pending_refby = _safe_referenced_by_items(project_key)
        pending_publishable = tuple(
            item for item in pending_active if _publication_is_ready(item)
        )
        if pending_active and not pending_publishable and result.outcome == "idle":
            result.outcome = "awaiting_done_marker"
        elif pending_publishable and result.outcome == "idle":
            result.outcome = "active_remaining"
        elif pending_refby and result.outcome == "idle":
            result.outcome = "referenced_by_remaining"
        elif result.outcome == "idle" and (
            result.hood_drained or result.link_drained or result.referenced_by_drained
        ):
            result.outcome = "drained"

        if not result.preserve_hints:
            finish_hint_claim(claim)
        return result
    except BaseException:
        # Leave the renamed claim in place; the next pass re-merges it.
        raise


def _hinted_keys(
    claim: PublicationHintClaim,
    active: dict[tuple[str, str], AgentPublicationOutboxItem],
) -> tuple[tuple[str, str], ...]:
    keys: list[tuple[str, str]] = []
    for hint in claim.hints:
        key = (hint["global_agent"], hint["primary_revision"])
        if key in active and key not in keys:
            keys.append(key)
    return tuple(keys)


def _hinted_link_agents(claim: PublicationHintClaim) -> frozenset[str]:
    return frozenset(
        hint["link_outbox_agent_name"]
        for hint in claim.hints
        if hint["link_outbox_agent_name"]
    )


def _made_progress(
    before: tuple[AgentPublicationOutboxItem, ...],
    after: tuple[AgentPublicationOutboxItem, ...],
    outcome: CommitPublicationOutcome,
) -> bool:
    return outcome.drained > 0 or {item.logical_key for item in before} != {
        item.logical_key for item in after
    }


def _is_lock_busy(outcome: CommitPublicationOutcome) -> bool:
    diagnostic = " ".join((outcome.error or "", outcome.skip_reason or ""))
    return _LOCK_BUSY_TEXT in diagnostic


def _safe_active_items(project_key: str) -> tuple[AgentPublicationOutboxItem, ...]:
    try:
        return active_agent_publications(project_key)
    except Exception:
        return ()


def _publication_is_ready(
    item: AgentPublicationOutboxItem,
    *,
    now: float | None = None,
) -> bool:
    """Wait briefly for done.json before publishing a newly queued run."""

    if not item.artifacts_dir:
        return True
    if (Path(item.artifacts_dir).expanduser() / "done.json").is_file():
        return True
    observed = time.time() if now is None else now
    return observed - item.created_at >= _DONE_MARKER_GRACE_SECONDS


def _safe_active_count(project_key: str) -> int:
    return len(_safe_active_items(project_key))


def _oldest_age(
    items: tuple[AgentPublicationOutboxItem, ...], *, now: float | None = None
) -> float:
    if not items:
        return 0.0
    observed = time.time() if now is None else now
    created = min(item.created_at for item in items)
    return max(0.0, observed - created)


def _oldest_active_age(project_key: str) -> float:
    return _oldest_age(_safe_active_items(project_key))


def _safe_referenced_by_items(project_key: str) -> tuple[Any, ...]:
    try:
        return list_referenced_by_requests(project_key, include_quarantined=False)
    except Exception:
        return ()


def _safe_referenced_by_count(project_key: str) -> int:
    return len(_safe_referenced_by_items(project_key))


def _safe_ring(project_key: str) -> None:
    try:
        ring_publication_doorbell(project_key)
    except Exception:
        return


__all__ = [
    "PUBLICATION_JOB_WORK_BUDGET_SECONDS",
    "run_publication_job",
]
