"""Report-first repair for stale publication-revision outbox rows.

Rows enqueued before the post-commit revision fix can name a primary revision
that no published run carries. This repair classifies each queued request and,
when requested, rewrites the outbox through its mutation API while preserving
request history and auditing every applied change.
"""

from __future__ import annotations

from sase.agents_sync import _commit_publication_support as publication_support
from sase.agents_sync._publication_revision_repair_apply import (
    apply_project_revisions,
)
from sase.agents_sync._publication_revision_repair_classification import (
    classify_project_revisions,
)
from sase.agents_sync.git import GitRunner, run_git
from sase.agents_sync.git_sync import ensure_agents_clone
from sase.agents_sync.git_sync_ops import (
    agents_git_dir,
    bounded_agents_lock,
    configured_agents_lock_timeout,
)
from sase.agents_sync.models import ProjectTarget, SyncOutcome
from sase.agents_sync._publication_revision_repair_models import (
    REPAIR_REVISIONS_APPLY_COMMAND,
    REPAIR_REVISIONS_AUDIT_FILENAME,
    REPAIR_REVISIONS_COMMAND,
)
from sase.core.agent_identity_facade import AgentOwnerIdentity


def repair_stale_publication_revisions(
    projects: tuple[str, ...] = (),
    *,
    apply: bool = False,
    git_runner: GitRunner = run_git,
    lock_timeout_seconds: float | None = None,
) -> tuple[SyncOutcome, ...]:
    """Classify stale publication revisions for selected projects.

    Report mode (``apply=False``) writes nothing. Apply mode rewrites the
    outbox through the outbox mutation APIs and appends an audit JSONL.
    """

    selection = publication_support.resolve_sync_targets(projects)
    outcomes = list(selection.outcomes)
    try:
        owner = publication_support.require_agent_owner_identity()
    except (RuntimeError, ValueError) as exc:
        outcomes.extend(
            SyncOutcome(
                target.project_key,
                target.project,
                error=f"owner identity is not configured: {exc}",
            )
            for target in selection.targets
        )
        return tuple(sorted(outcomes, key=lambda item: item.project_key))

    for target in selection.targets:
        try:
            outcomes.append(
                _repair_project_revisions(
                    target,
                    owner,
                    apply=apply,
                    git_runner=git_runner,
                    lock_timeout_seconds=lock_timeout_seconds,
                )
            )
        except Exception as exc:  # noqa: BLE001 - per-project isolation contract
            outcomes.append(
                SyncOutcome(
                    target.project_key,
                    target.project,
                    error=f"agents revision repair failed: {exc}",
                )
            )
    return tuple(sorted(outcomes, key=lambda item: item.project_key))


def _repair_project_revisions(
    target: ProjectTarget,
    owner: AgentOwnerIdentity,
    *,
    apply: bool,
    git_runner: GitRunner = run_git,
    lock_timeout_seconds: float | None = None,
) -> SyncOutcome:
    """Repair one project's stale outbox revisions under the agents lock."""

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
        report = classify_project_revisions(target, owner, git_runner=git_runner)
        if apply:
            report = apply_project_revisions(target, report)
        return SyncOutcome(
            target.project_key, target.project, diagnostics=report.diagnostics()
        )


__all__ = [
    "REPAIR_REVISIONS_APPLY_COMMAND",
    "REPAIR_REVISIONS_AUDIT_FILENAME",
    "REPAIR_REVISIONS_COMMAND",
    "repair_stale_publication_revisions",
]
