"""Report-first repair of evidence-proven planner publication rows."""

from __future__ import annotations

from sase.agents_sync import _commit_publication_support as publication_support
from sase.agents_sync._publication_planner_scope_repair_apply import (
    apply_project_planner_scopes,
)
from sase.agents_sync._publication_planner_scope_repair_classification import (
    classify_project_planner_scopes,
)
from sase.agents_sync.git import GitRunner, run_git
from sase.agents_sync.git_sync import ensure_agents_clone
from sase.agents_sync.git_sync_ops import (
    agents_git_dir,
    bounded_agents_lock,
    configured_agents_lock_timeout,
)
from sase.agents_sync.models import ProjectTarget, SyncOutcome
from sase.agents_sync._publication_planner_scope_repair_models import (
    REPAIR_PLANNER_SCOPES_APPLY_COMMAND,
    REPAIR_PLANNER_SCOPES_AUDIT_FILENAME,
    REPAIR_PLANNER_SCOPES_COMMAND,
)


def repair_planner_publication_scopes(
    projects: tuple[str, ...] = (),
    *,
    apply: bool = False,
    git_runner: GitRunner = run_git,
    lock_timeout_seconds: float | None = None,
) -> tuple[SyncOutcome, ...]:
    """Classify one project's revision rows and optionally re-scope proven planners."""

    selection = publication_support.resolve_sync_targets(projects)
    outcomes = list(selection.outcomes)
    if len(selection.targets) != 1:
        if not outcomes:
            outcomes.append(
                SyncOutcome(
                    "project-selection",
                    "project selection",
                    error=(
                        f"{REPAIR_PLANNER_SCOPES_COMMAND} requires exactly one "
                        "selected project"
                    ),
                )
            )
        return tuple(sorted(outcomes, key=lambda item: item.project_key))

    target = selection.targets[0]
    try:
        outcome = _repair_project_planner_scopes(
            target,
            apply=apply,
            git_runner=git_runner,
            lock_timeout_seconds=lock_timeout_seconds,
        )
    except Exception as exc:  # noqa: BLE001 - project failure becomes visible output.
        outcome = SyncOutcome(
            target.project_key,
            target.project,
            error=f"agents planner scope repair failed: {exc}",
        )
    outcomes.append(outcome)
    return tuple(sorted(outcomes, key=lambda item: item.project_key))


def _repair_project_planner_scopes(
    target: ProjectTarget,
    *,
    apply: bool,
    git_runner: GitRunner,
    lock_timeout_seconds: float | None,
) -> SyncOutcome:
    """Classify and optionally apply rows while holding the agents lock."""

    timeout = (
        configured_agents_lock_timeout()
        if lock_timeout_seconds is None
        else max(lock_timeout_seconds, 0.0)
    )
    if not target.primary_checkout.is_dir():
        return SyncOutcome(
            target.project_key,
            target.project,
            error="primary checkout does not exist",
        )
    clone_error = ensure_agents_clone(
        target, git_runner=git_runner, lock_timeout_seconds=timeout
    )
    if clone_error is not None:
        if clone_error == "agents sync clone lock is busy":
            return SyncOutcome(
                target.project_key, target.project, skip_reason=clone_error
            )
        return SyncOutcome(target.project_key, target.project, error=clone_error)

    lock_path = (
        agents_git_dir(target.sidecar_path, git_runner) / "sase-agents-sync.lock"
    )
    with bounded_agents_lock(lock_path, timeout) as acquired:
        if not acquired:
            return SyncOutcome(
                target.project_key,
                target.project,
                skip_reason="agents sync lock is busy",
            )
        report = classify_project_planner_scopes(target, git_runner=git_runner)
        if apply:
            report = apply_project_planner_scopes(target, report)
        return SyncOutcome(
            target.project_key,
            target.project,
            error=report.evidence_error,
            diagnostics=report.diagnostics(),
        )


__all__ = [
    "REPAIR_PLANNER_SCOPES_APPLY_COMMAND",
    "REPAIR_PLANNER_SCOPES_AUDIT_FILENAME",
    "REPAIR_PLANNER_SCOPES_COMMAND",
    "repair_planner_publication_scopes",
]
