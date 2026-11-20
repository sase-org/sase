"""Scheduler pass for the agent publication job."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
import fcntl
import os
import time

from sase.agents_sync._publication_job_drain import drain_project
from sase.agents_sync._publication_job_shared import (
    ProjectPass,
    PublicationJobSummary,
    publication_is_ready,
    safe_active_items,
    safe_referenced_by_count,
)
from sase.agents_sync.git import GitRunner, run_git
from sase.agents_sync.models import ProjectTarget, SyncOutcome
from sase.agents_sync.publication_diverged_replay import read_diverged_replay_marker
from sase.agents_sync.publication_doorbell import (
    ring_publication_doorbell,
    write_publication_heartbeat,
)
from sase.agents_sync.publication_outbox import AgentPublicationOutboxItem
from sase.agents_sync.publication_standing import (
    StandingReport,
    apply_project_observations,
    blocking_alerts,
    has_open_alert_of_kind,
    is_due,
    load_standing_alerts,
    open_alert_count,
    project_standing_stats,
    repeat_blocked_ticks,
    report_standing_transition,
    save_standing_alerts,
)
from sase.agents_sync.targets import resolve_sync_targets
from sase.core.agent_publication_standing import (
    STANDING_KIND_ARTIFACT_LINK,
    STANDING_KIND_CHARGED_ITEM,
    STANDING_KIND_DRAIN_ERROR,
    STANDING_KIND_DRAIN_TIMEOUT,
    STANDING_KIND_HEARTBEAT_WRITE,
    STANDING_KIND_LOCK_BUSY,
    STANDING_KIND_REFERENCED_BY,
    STANDING_KIND_SELECTION_ERROR,
    STANDING_KIND_TARGET_UNAVAILABLE,
    STANDING_TRANSITION_CHANGED,
    STANDING_TRANSITION_CLEARED,
    STANDING_TRANSITION_ESCALATED,
    STANDING_TRANSITION_OPENED,
)
from sase.core.paths import sase_home, sase_projects_dir
from sase.core.project_lifecycle_facade import list_project_records

PUBLICATION_JOB_WORK_BUDGET_SECONDS = 240.0

# Machine-wide failures (project listing, target resolution, heartbeat write)
# are keyed to a pseudo-project that can never collide with a real project.
_PUBLISHER_STANDING_PROJECT = "*publisher*"


def run_publication_job(
    *,
    git_runner: GitRunner = run_git,
    work_budget_seconds: float = PUBLICATION_JOB_WORK_BUDGET_SECONDS,
) -> PublicationJobSummary:
    """Drain enabled projects, then write the publisher heartbeat."""

    with _publisher_job_lock() as acquired:
        if not acquired:
            return PublicationJobSummary(skipped_overlap=True)
        return _run_publication_job(
            git_runner=git_runner,
            work_budget_seconds=work_budget_seconds,
        )


def _run_publication_job(
    *,
    git_runner: GitRunner,
    work_budget_seconds: float,
) -> PublicationJobSummary:
    """Execute one pass while the process-wide publisher lock is held."""

    summary = PublicationJobSummary()
    started = time.monotonic()
    deadline = started + max(0.0, work_budget_seconds)
    # Machine-wide failures fold into one standing apply after the heartbeat
    # write, so each reports only its transitions and a clean pass clears it.
    publisher_observations: list[tuple[str, str]] = []
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
        publisher_observations.append(
            (STANDING_KIND_SELECTION_ERROR, f"could not list enabled projects: {exc}")
        )
        project_keys = ()
    targets: dict[str, ProjectTarget] = {}
    outcomes_by_key: dict[str, SyncOutcome] = {}
    selection_errors: dict[str, str] = {}
    if project_keys:
        try:
            selection = resolve_sync_targets(project_keys)
            targets = {target.project_key: target for target in selection.targets}
            outcomes_by_key = {
                outcome.project_key: outcome for outcome in selection.outcomes
            }
            for outcome in selection.outcomes:
                if outcome.error:
                    # Counted per project below through the standing decider,
                    # so a repeated failure reports only its transition.
                    selection_errors[outcome.project_key] = outcome.error
        except Exception as exc:  # noqa: BLE001 - projects are retried next tick.
            publisher_observations.append(
                (
                    STANDING_KIND_SELECTION_ERROR,
                    f"could not resolve publication targets: {exc}",
                )
            )
    standing_alerts = load_standing_alerts()
    standing_now = time.time()

    summary.projects = len(project_keys)
    for index, project_key in enumerate(project_keys):
        if blocking_alerts(standing_alerts, project_key, standing_now):
            # A project-scoped alert is backing off: skip the drain and the
            # doorbell until it is due. Queued hints stay queued because no
            # claim is taken, and the trigger's max_quiet backstop re-runs
            # the job. Attempt counts still tick so the record stays true.
            for blocked_report in repeat_blocked_ticks(
                standing_alerts, project_key, now=standing_now
            ):
                _count_standing_report(
                    summary, project_key, blocked_report, standing_now
                )
            _defer_selection_error(
                summary,
                project_key,
                selection_errors,
                tracked=has_open_alert_of_kind(
                    standing_alerts, project_key, STANDING_KIND_SELECTION_ERROR
                ),
            )
            blocked_active = safe_active_items(project_key)
            blocked_parked = _parked_items(blocked_active)
            summary.active_remaining += len(blocked_active)
            summary.parked += len(blocked_parked)
            summary.project_stats[project_key] = {
                "active_count": len(blocked_active),
                "oldest_active_age_seconds": _oldest_age(blocked_active),
                "parked_count": len(blocked_parked),
                "oldest_parked_age_seconds": _oldest_parked_age(blocked_parked),
                "last_outcome": "standing_backoff",
                **project_standing_stats(standing_alerts, project_key),
            }
            continue
        if time.monotonic() >= deadline:
            summary.deferred_projects += len(project_keys) - index
            for deferred_key in project_keys[index:]:
                deferred_active = safe_active_items(deferred_key)
                deferred_parked = _parked_items(deferred_active)
                deferred_parked_count = len(deferred_parked)
                summary.parked += deferred_parked_count
                summary.project_stats[deferred_key] = {
                    "active_count": len(deferred_active),
                    "oldest_active_age_seconds": _oldest_age(deferred_active),
                    "parked_count": deferred_parked_count,
                    "oldest_parked_age_seconds": _oldest_parked_age(deferred_parked),
                    "last_outcome": "deferred_budget",
                    **project_standing_stats(standing_alerts, deferred_key),
                }
                if read_diverged_replay_marker(deferred_key) is None and is_due(
                    standing_alerts, deferred_key, standing_now
                ):
                    _safe_ring(deferred_key)
                _defer_selection_error(
                    summary,
                    deferred_key,
                    selection_errors,
                    tracked=has_open_alert_of_kind(
                        standing_alerts, deferred_key, STANDING_KIND_SELECTION_ERROR
                    ),
                )
            break
        observations: list[tuple[str, str]] = []
        selection_error = selection_errors.pop(project_key, None)
        if selection_error is not None:
            observations.append((STANDING_KIND_SELECTION_ERROR, selection_error))
        target = targets.get(project_key)
        if target is None:
            # A missing target cannot be drained, so the job never rings the
            # doorbell here: the trigger's max_quiet backstop re-runs the job,
            # and queued hints stay in the hints file because no claim is
            # taken, so nothing is lost when the target comes back.
            missing_active = safe_active_items(project_key)
            missing_parked = _parked_items(missing_active)
            missing_parked_count = len(missing_parked)
            summary.parked += missing_parked_count
            summary.active_remaining += len(missing_active)
            missing_outcome = outcomes_by_key.get(project_key)
            if missing_outcome is not None and missing_outcome.error:
                # Already recorded once as a selection observation above; do
                # not record a second observation.
                last_outcome = "target_unavailable"
            else:
                skip_reason = (
                    missing_outcome.skip_reason
                    if missing_outcome is not None and missing_outcome.skip_reason
                    else "no usable agents publication target"
                )
                if missing_active:
                    observations.append(
                        (
                            STANDING_KIND_TARGET_UNAVAILABLE,
                            f"{len(missing_active)} queued publication "
                            f"request(s) cannot drain: {skip_reason}",
                        )
                    )
                    last_outcome = "target_unavailable"
                else:
                    # Nothing queued is silently clean: the b0de76422d
                    # no-target-with-nothing-queued case stays silent, and a
                    # clean pass clears any open alert for this project.
                    last_outcome = "target_skipped"
            for missing_report in apply_project_observations(
                standing_alerts,
                project_key,
                observations,
                now=standing_now,
                clean=not observations,
            ):
                _count_standing_report(
                    summary, project_key, missing_report, standing_now
                )
            summary.project_stats[project_key] = {
                "active_count": len(missing_active),
                "oldest_active_age_seconds": _oldest_age(missing_active),
                "parked_count": missing_parked_count,
                "oldest_parked_age_seconds": _oldest_parked_age(missing_parked),
                "last_outcome": last_outcome,
                **project_standing_stats(standing_alerts, project_key),
            }
            continue
        try:
            result = drain_project(
                target,
                deadline=deadline,
                git_runner=git_runner,
            )
        except Exception as exc:  # noqa: BLE001 - one project cannot starve others.
            result = ProjectPass(
                error=str(exc) or type(exc).__name__,
                claim_unfinished=True,
                outcome="error",
            )
        summary.hood_drained += result.hood_drained
        summary.link_drained += result.link_drained
        summary.referenced_by_drained += result.referenced_by_drained
        summary.lock_busy += int(result.lock_busy)
        summary.deferred_projects += int(result.deferred)
        if result.error:
            observations.append((_standing_kind_for_result(result), result.error))
        clean_pass = (
            not observations
            and not result.deferred
            and not result.lock_busy
            and not result.outcome.startswith("diverged_replay")
        )
        for drain_report in apply_project_observations(
            standing_alerts,
            project_key,
            observations,
            now=standing_now,
            clean=clean_pass,
        ):
            _count_standing_report(summary, project_key, drain_report, standing_now)
        active = safe_active_items(project_key)
        active_count = len(active)
        summary.active_remaining += active_count
        parked_items = _parked_items(active)
        parked_count = len(parked_items)
        summary.parked += parked_count
        publishable_count = sum(publication_is_ready(item) for item in active)
        refby_count = safe_referenced_by_count(project_key)
        if (
            (
                publishable_count
                or refby_count
                or result.lock_busy
                or result.deferred
                or result.retained_hints
                or result.claim_unfinished
            )
            and not result.outcome.startswith("diverged_replay")
            and is_due(standing_alerts, project_key, standing_now)
        ):
            _safe_ring(project_key)
        summary.project_stats[project_key] = {
            "active_count": active_count,
            "oldest_active_age_seconds": _oldest_age(active),
            "parked_count": parked_count,
            "oldest_parked_age_seconds": _oldest_parked_age(parked_items),
            "last_outcome": result.outcome,
            **project_standing_stats(standing_alerts, project_key),
        }

    # Every listed project pops its own selection error above. An outcome
    # keyed to a project outside the listing can never be processed, so it is
    # recorded on the publisher pseudo-project, where a later clean pass
    # clears it.
    for leftover_key in sorted(selection_errors):
        publisher_observations.append(
            (
                STANDING_KIND_SELECTION_ERROR,
                f"{leftover_key}: {selection_errors[leftover_key]}",
            )
        )

    # The heartbeat write is machine-wide too. Every publisher observation
    # folds into one apply, because a pass clears any publisher alert it did
    # not observe: a failure reports only its transition, a clean pass clears.
    try:
        write_publication_heartbeat(summary.project_stats)
    except Exception as exc:  # noqa: BLE001 - the next pass retries heartbeat.
        publisher_observations.append(
            (
                STANDING_KIND_HEARTBEAT_WRITE,
                f"could not write publisher heartbeat: {exc}",
            )
        )
    for publisher_report in apply_project_observations(
        standing_alerts,
        _PUBLISHER_STANDING_PROJECT,
        publisher_observations,
        now=standing_now,
        clean=not publisher_observations,
    ):
        _count_standing_report(
            summary, _PUBLISHER_STANDING_PROJECT, publisher_report, standing_now
        )

    summary.standing = open_alert_count(standing_alerts)
    save_standing_alerts(standing_alerts)
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


def _parked_items(
    items: tuple[AgentPublicationOutboxItem, ...],
) -> tuple[AgentPublicationOutboxItem, ...]:
    """Return the parked subset of *items*."""

    return tuple(item for item in items if item.parked_reason is not None)


def _oldest_parked_age(
    items: tuple[AgentPublicationOutboxItem, ...], *, now: float | None = None
) -> float:
    """Return the greatest parked age, or 0.0 when nothing is parked."""

    if not items:
        return 0.0
    observed = time.time() if now is None else now
    ages: list[float] = []
    for item in items:
        base = item.parked_since
        if base is None:
            base = item.parked_checked_at
        if base is None:
            base = item.created_at
        ages.append(max(0.0, observed - base))
    return max(ages) if ages else 0.0


def _oldest_age(
    items: tuple[AgentPublicationOutboxItem, ...], *, now: float | None = None
) -> float:
    if not items:
        return 0.0
    observed = time.time() if now is None else now
    created = min(item.created_at for item in items)
    return max(0.0, observed - created)


def _defer_selection_error(
    summary: PublicationJobSummary,
    project_key: str,
    selection_errors: dict[str, str],
    *,
    tracked: bool,
) -> None:
    """Leave a skipped project's selection error for its next processed pass.

    A project skipped this tick (budget-deferred or backing off) is not
    charged: its next processed pass records the error through the standing
    decider, which reports only transitions. When *tracked* (an open
    selection-error alert already covers the project) it stays quiet;
    otherwise it is noted so the log still explains the skipped error.
    """

    error = selection_errors.pop(project_key, None)
    if error is None or tracked:
        return
    summary.diagnostics.append(
        f"{project_key}: selection error left for the next processed pass: {error}"
    )


def _safe_ring(project_key: str) -> None:
    try:
        ring_publication_doorbell(project_key)
    except Exception:
        return


def _standing_kind_for_result(result: ProjectPass) -> str:
    """Map one failed project pass to its standing failure kind."""

    if result.lock_busy:
        return STANDING_KIND_LOCK_BUSY
    detail = (result.error or "").lower()
    if "did not complete within" in detail:
        return STANDING_KIND_DRAIN_TIMEOUT
    if result.outcome == "link_error" or "artifact-link" in detail:
        return STANDING_KIND_ARTIFACT_LINK
    if result.outcome == "referenced_by_error" or "referenced-by" in detail:
        return STANDING_KIND_REFERENCED_BY
    if result.outcome == "hood_error":
        # Row-scoped: attempt counts, quarantine, and parking already govern
        # these, so they take no project backoff.
        return STANDING_KIND_CHARGED_ITEM
    return STANDING_KIND_DRAIN_ERROR


def _count_standing_report(
    summary: PublicationJobSummary,
    project_key: str,
    report: StandingReport,
    now: float,
) -> None:
    """Count one standing report exactly like today's error counting.

    Only reported transitions (opened, changed, escalated) and fallback
    reports count an error and keep the legacy diagnostic text; cleared only
    fires the quiet +1 note on its row.
    """

    if report.transition in (
        STANDING_TRANSITION_OPENED,
        STANDING_TRANSITION_CHANGED,
        STANDING_TRANSITION_ESCALATED,
    ):
        summary.errors += 1
        summary.diagnostics.append(f"{project_key}: {report.detail}")
        # The chop summary grammar takes one whitespace-free reason token,
        # so transitions join as colon-separated segments.
        summary.standing_report.append(
            f"{project_key}:{report.transition}:{report.failure_kind}"
            f":attempt{report.attempts}"
        )
        report_standing_transition(report, now=now)
    elif report.transition == STANDING_TRANSITION_CLEARED:
        report_standing_transition(report, now=now)
    else:
        # Classifier trouble falls back to today's counting so the failure
        # stays visible instead of staying silent.
        summary.errors += 1
        summary.diagnostics.append(f"{project_key}: {report.detail}")
