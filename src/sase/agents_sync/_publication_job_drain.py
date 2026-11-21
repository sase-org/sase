"""Single-project drain pass for the agent publication job."""

from __future__ import annotations

from collections.abc import Callable
import logging
import time
from typing import Any

from sase.agents_sync._commit_publication_types import (
    REPOSITORY_FAILURE_SCOPE,
    CommitPublicationOutcome,
)
from sase.agents_sync._publication_job_shared import (
    ProjectPass,
    active_items,
    publication_is_ready,
    safe_referenced_by_items,
)
from sase.agents_sync.git import GitRunner
from sase.agents_sync.models import ProjectTarget
from sase.agents_sync.publication_diverged_replay import (
    PUBLICATION_REBASE_FAILURE_STAGE,
    active_diverged_replay_marker,
    read_diverged_replay_marker,
)
from sase.agents_sync.publication_doorbell import (
    PublicationHintClaim,
    claim_publication_hints,
    finish_hint_claim,
)
from sase.agents_sync.publication_outbox import AgentPublicationOutboxItem
from sase.agents_sync.publication_outbox_models import publication_sort_key
from sase.sdd.artifact_link_outbox import drain_artifact_link_outbox
from sase.sdd.artifact_link_store import resolve_machine_artifact_link_store

_HOOD_BATCH_LIMIT = 25
# Mirrors the artifact_link_backfill drain-phase line so both chops' logs read
# the same way; ``publish.*`` sub-phases sit right after their parent.
_LINK_DRAIN_PHASES = (
    "read",
    "evidence",
    "eligibility",
    "catalog",
    "publish",
    "rewrite",
)
_LINK_PUBLISH_PHASE_PREFIX = "publish."
_LOCK_BUSY_TEXT = "agents sync lock is busy"
_log = logging.getLogger(__name__)


def drain_project(
    target: ProjectTarget,
    *,
    deadline: float,
    git_runner: GitRunner,
    progress: Callable[[str], None] | None = None,
) -> ProjectPass:
    """Drain one project; *progress* gets a line before each stage starts.

    Lines are emitted before the stage's work so a SIGKILL leaves the last
    stage that began.
    """

    from sase.agents_sync._commit_publication_queue import (
        drain_selected_agent_publications,
    )
    from sase.agents_sync.inventory_reuse import ProjectHoodInventoryReuse
    from sase.agents_sync.referenced_by_publication import drain_referenced_by_requests

    def _stage(message: str) -> None:
        if progress is not None:
            progress(message)

    project_key = target.project_key
    parked_marker = active_diverged_replay_marker(
        project_key,
        target.sidecar_path,
        git_runner,
    )
    if parked_marker is not None:
        return ProjectPass(deferred=True, outcome="diverged_replay_parked")
    claim = claim_publication_hints(project_key)
    result = ProjectPass()
    try:
        pass_hoods = frozenset(
            item.local_hood
            for item in active_items(project_key)
            if publication_is_ready(item)
        )
        inventory_reuse = ProjectHoodInventoryReuse(pass_hoods)
        attempted: set[tuple[str, str]] = set()
        stop_for_repository_failure = False
        batch_number = 0
        while time.monotonic() < deadline:
            before = tuple(
                item for item in active_items(project_key) if publication_is_ready(item)
            )
            active_by_key = {item.logical_key: item for item in before}
            hinted_keys = _hinted_keys(claim, active_by_key)
            hinted_order = tuple(key for key in hinted_keys if key not in attempted)
            hinted_set = frozenset(hinted_order)
            fallback_order = tuple(
                item.logical_key
                for item in sorted(before, key=publication_sort_key)
                if item.logical_key not in attempted
                and item.logical_key not in hinted_set
            )
            batch = (*hinted_order, *fallback_order)[:_HOOD_BATCH_LIMIT]
            if not batch:
                break

            # Attempted keys stay excluded even if this batch makes no progress.
            attempted.update(batch)
            batch_number += 1
            _stage(f"hood batch {batch_number} ({len(batch)} keys)")
            outcome = drain_selected_agent_publications(
                project_key,
                tuple(batch),
                git_runner=git_runner,
                inventory_reuse=inventory_reuse,
            )
            result.hood_drained += outcome.drained
            if outcome.failure_stage == PUBLICATION_REBASE_FAILURE_STAGE:
                result.deferred = True
                result.outcome = "diverged_replay"
                stop_for_repository_failure = True
                break
            diagnostic = outcome.error or outcome.skip_reason
            if _is_lock_busy(outcome):
                result.lock_busy = True
                result.outcome = "lock_busy"
                _append_project_error(result, diagnostic or "agents sync lock is busy")
                stop_for_repository_failure = True
                break
            if diagnostic:
                _append_project_error(result, diagnostic)
            if outcome.failure_scope == REPOSITORY_FAILURE_SCOPE:
                result.outcome = "repository_error"
                stop_for_repository_failure = True
                break
            # Row-scoped failures and no-progress batches do not starve the
            # project: their keys are attempted, so the next iteration moves on.

        ready_after = tuple(
            item for item in active_items(project_key) if publication_is_ready(item)
        )
        ready_keys = {item.logical_key for item in ready_after}
        unattempted = ready_keys - attempted
        budget_expired = time.monotonic() >= deadline
        if budget_expired and unattempted:
            result.deferred = True
            result.outcome = "deferred_budget"
        if unattempted and (
            budget_expired or stop_for_repository_failure or result.lock_busy
        ):
            result.retained_hints.extend(
                _claim_hints_for_work(claim, hood_keys=unattempted)
            )

        if result.outcome == "diverged_replay":
            finish_hint_claim(claim, retain=result.retained_hints)
            return result

        link_agents = _hinted_link_agents(claim)
        if link_agents and time.monotonic() < deadline:
            try:
                _stage("link store resolve")
                store = resolve_machine_artifact_link_store(
                    project_key,
                    target.primary_checkout,
                    deadline=deadline,
                )
                _stage(f"link drain ({len(link_agents)} agents)")
                link_report = drain_artifact_link_outbox(
                    store=store,
                    agent_names=link_agents,
                    drop_stale_terminal=False,
                    deadline=deadline,
                )
                _stage(_link_phase_line(link_report))
                result.link_drained += link_report.drained
                if link_report.selected_retained:
                    result.link_retained += link_report.selected_retained
                if link_report.deferred:
                    result.retained_hints.extend(
                        _claim_hints_for_work(claim, link_agents=link_agents)
                    )
                    result.deferred = True
                    result.outcome = "deferred_budget"
            except Exception as exc:  # noqa: BLE001 - hints retry on next pass.
                _append_project_error(result, f"artifact-link drain failed: {exc}")
                result.retained_hints.extend(
                    _claim_hints_for_work(claim, link_agents=link_agents)
                )
                result.outcome = "link_error"
        elif link_agents:
            result.retained_hints.extend(
                _claim_hints_for_work(claim, link_agents=link_agents)
            )
            result.deferred = True
            result.outcome = "deferred_budget"

        pending_refby = safe_referenced_by_items(project_key)
        if pending_refby and time.monotonic() < deadline:
            try:
                _stage("referenced-by drain")
                before_count = len(pending_refby)
                diagnostics = drain_referenced_by_requests(
                    target,
                    git_runner=git_runner,
                )
                after_count = len(safe_referenced_by_items(project_key))
                result.referenced_by_drained += max(0, before_count - after_count)
                if diagnostics:
                    result.error = "; ".join(diagnostics)
                    if result.outcome == "idle":
                        result.outcome = "referenced_by_error"
            except Exception as exc:  # noqa: BLE001 - retry on the next tick.
                result.error = f"referenced-by drain failed: {exc}"
                if result.outcome == "idle":
                    result.outcome = "referenced_by_error"

        if not stop_for_repository_failure and time.monotonic() < deadline:
            _stage("quarantine sweep")
            _sweep_quarantined_prompts(target, deadline=deadline, git_runner=git_runner)

        pending_active = active_items(project_key)
        pending_refby = safe_referenced_by_items(project_key)
        pending_publishable = tuple(
            item for item in pending_active if publication_is_ready(item)
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

        if result.link_retained:
            detail = f"{result.link_retained} artifact-link rows retained for backfill"
            result.outcome = (
                detail if result.outcome == "idle" else f"{result.outcome}; {detail}"
            )

        finish_hint_claim(claim, retain=result.retained_hints)
        return result
    except BaseException:
        # Leave the renamed claim in place; the next pass re-merges it.
        raise


def _link_phase_line(report: object) -> str:
    """Render the link drain's per-phase timings like the backfill chop does."""

    phases = dict(getattr(report, "phase_seconds", ()) or ())
    parts: list[str] = []
    for name in _LINK_DRAIN_PHASES:
        value = phases.get(name)
        parts.append(f"{name}={'skipped' if value is None else f'{value:.2f}s'}")
        if name == "publish":
            parts.extend(
                f"{key}={seconds:.2f}s"
                for key, seconds in phases.items()
                if key.startswith(_LINK_PUBLISH_PHASE_PREFIX)
            )
    return "link drain phases: " + " ".join(parts)


def _sweep_quarantined_prompts(
    target: ProjectTarget,
    *,
    deadline: float,
    git_runner: GitRunner,
) -> None:
    """Retire a bounded batch of unrecoverable quarantined prompt rows.

    The sweep is housekeeping on rows that already left the active queue, so
    its trouble is logged and retried next pass, never a project error.
    """

    from sase.agents_sync.prompt_archive.quarantine_sweep import (
        sweep_quarantined_prompt_archives,
    )

    try:
        sweep_quarantined_prompt_archives(
            target,
            git_runner=git_runner,
            deadline=deadline,
        )
    except Exception:  # noqa: BLE001 - housekeeping retries on the next pass.
        _log.warning(
            "quarantined prompt sweep failed for %s",
            target.project_key,
            exc_info=True,
        )


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


def _claim_hints_for_work(
    claim: PublicationHintClaim,
    *,
    hood_keys: set[tuple[str, str]] | frozenset[tuple[str, str]] = frozenset(),
    link_agents: frozenset[str] = frozenset(),
) -> list[dict[str, Any]]:
    """Return only claimed hints that still identify deferred work."""

    return [
        hint
        for hint in claim.hints
        if (
            (hint["global_agent"], hint["primary_revision"]) in hood_keys
            or hint["link_outbox_agent_name"] in link_agents
        )
    ]


def _append_project_error(result: ProjectPass, diagnostic: str) -> None:
    """Accumulate distinct diagnostics without stopping row-scoped work."""

    messages = result.error.split("; ") if result.error else []
    if diagnostic not in messages:
        messages.append(diagnostic)
    result.error = "; ".join(messages)
    if result.outcome == "idle":
        result.outcome = "hood_error"


def _is_lock_busy(outcome: CommitPublicationOutcome) -> bool:
    diagnostic = " ".join((outcome.error or "", outcome.skip_reason or ""))
    return _LOCK_BUSY_TEXT in diagnostic
