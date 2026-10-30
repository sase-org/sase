"""Public state-repair orchestration and preview handling."""

from __future__ import annotations

import time

from sase.agents_sync import _commit_publication_support as publication_support
from sase.agents_sync.git import GitRunner, run_git
from sase.agents_sync.git_sync import ensure_agents_clone
from sase.agents_sync.git_sync_ops import (
    agents_git_dir,
    bounded_agents_lock,
    configured_agents_lock_timeout,
)
from sase.agents_sync.inventory import ProjectHoodInventory
from sase.agents_sync.models import ProjectTarget
from sase.agents_sync.v2_io import MAX_PAYLOAD_BYTES
from sase.core.agent_identity_facade import AgentIdentitySnapshot, AgentOwnerIdentity
from sase.agents_sync._publication_state_repair_evidence import (
    collect_published_rows,
    default_inventory_loader,
    resolve_selected,
    select_window,
)
from sase.agents_sync._publication_state_repair_push import plan_and_push_repair
from sase.agents_sync._publication_state_repair_types import (
    InventoryLoader,
    STATE_REPAIR_DEFAULT_LIMIT,
    STATE_REPAIR_MAX_LIMIT,
    STATE_REPAIR_MIN_LIMIT,
    STATE_REPAIR_WORK_BUDGET_SECONDS,
    StateRepairReport,
    StateRepairWindowRow,
)


def repair_agent_run_states(
    projects: tuple[str, ...] = (),
    *,
    apply: bool = False,
    state_limit: int | None = None,
    state_after: str | None = None,
    git_runner: GitRunner = run_git,
    lock_timeout_seconds: float | None = None,
    inventory_loader: InventoryLoader | None = None,
    work_budget_seconds: float = STATE_REPAIR_WORK_BUDGET_SECONDS,
    payload_budget_bytes: int = MAX_PAYLOAD_BYTES,
) -> tuple[StateRepairReport, ...]:
    """Report (or apply) one bounded state window per selected project."""

    limit_error = _validate_limit(state_limit)
    if limit_error is not None:
        return (
            StateRepairReport(
                "", "", "apply" if apply else "preview", error=limit_error
            ),
        )
    selection = publication_support.resolve_sync_targets(tuple(projects))
    reports = [
        StateRepairReport(
            outcome.project_key,
            outcome.project,
            "apply" if apply else "preview",
            error=outcome.error,
            skip_reason=outcome.skip_reason,
            diagnostics=tuple(outcome.diagnostics),
        )
        for outcome in selection.outcomes
    ]
    try:
        owner = publication_support.require_agent_owner_identity()
    except (RuntimeError, ValueError) as exc:
        reports.extend(
            StateRepairReport(
                target.project_key,
                target.project,
                "apply" if apply else "preview",
                error=f"owner identity is not configured: {exc}",
            )
            for target in selection.targets
        )
        return tuple(sorted(reports, key=lambda item: item.project_key))
    limit = STATE_REPAIR_DEFAULT_LIMIT if state_limit is None else state_limit
    for target in selection.targets:
        try:
            reports.append(
                repair_project_run_states(
                    target,
                    owner,
                    apply=apply,
                    state_limit=limit,
                    state_after=state_after,
                    git_runner=git_runner,
                    lock_timeout_seconds=lock_timeout_seconds,
                    inventory_loader=inventory_loader,
                    work_budget_seconds=work_budget_seconds,
                    payload_budget_bytes=payload_budget_bytes,
                )
            )
        except Exception as exc:  # noqa: BLE001 - per-project isolation contract
            reports.append(
                StateRepairReport(
                    target.project_key,
                    target.project,
                    "apply" if apply else "preview",
                    error=f"agents state repair failed: {exc}",
                )
            )
    return tuple(sorted(reports, key=lambda item: item.project_key))


def _validate_limit(state_limit: int | None) -> str | None:
    if state_limit is None:
        return None
    if not STATE_REPAIR_MIN_LIMIT <= state_limit <= STATE_REPAIR_MAX_LIMIT:
        return (
            "state limit must be between "
            f"{STATE_REPAIR_MIN_LIMIT} and {STATE_REPAIR_MAX_LIMIT}"
        )
    return None


def repair_project_run_states(
    target: ProjectTarget,
    owner: AgentOwnerIdentity,
    *,
    apply: bool = False,
    state_limit: int = STATE_REPAIR_DEFAULT_LIMIT,
    state_after: str | None = None,
    git_runner: GitRunner = run_git,
    lock_timeout_seconds: float | None = None,
    inventory_loader: InventoryLoader | None = None,
    work_budget_seconds: float = STATE_REPAIR_WORK_BUDGET_SECONDS,
    payload_budget_bytes: int = MAX_PAYLOAD_BYTES,
) -> StateRepairReport:
    """Repair one project's published run states in a bounded window."""

    limit_error = _validate_limit(state_limit)
    if limit_error is not None:
        return StateRepairReport(
            target.project_key,
            target.project,
            "apply" if apply else "preview",
            error=limit_error,
        )
    loader = inventory_loader or default_inventory_loader
    if not apply:
        return _preview_project(
            target,
            owner,
            state_limit=state_limit,
            state_after=state_after,
            inventory_loader=loader,
            work_budget_seconds=work_budget_seconds,
        )
    timeout = (
        configured_agents_lock_timeout()
        if lock_timeout_seconds is None
        else max(lock_timeout_seconds, 0.0)
    )
    if not target.primary_checkout.is_dir():
        return StateRepairReport(
            target.project_key,
            target.project,
            "apply",
            error="primary checkout does not exist",
        )
    clone_error = ensure_agents_clone(
        target, git_runner=git_runner, lock_timeout_seconds=timeout
    )
    if clone_error is not None:
        if clone_error == "agents sync clone lock is busy":
            return StateRepairReport(
                target.project_key,
                target.project,
                "apply",
                skip_reason=clone_error,
            )
        return StateRepairReport(
            target.project_key, target.project, "apply", error=clone_error
        )
    lock_path = (
        agents_git_dir(target.sidecar_path, git_runner) / "sase-agents-sync.lock"
    )
    with bounded_agents_lock(lock_path, timeout) as acquired:
        if not acquired:
            return StateRepairReport(
                target.project_key,
                target.project,
                "apply",
                skip_reason="agents sync lock is busy",
            )
        return _apply_project_locked(
            target,
            owner,
            state_limit=state_limit,
            state_after=state_after,
            git_runner=git_runner,
            inventory_loader=loader,
            work_budget_seconds=work_budget_seconds,
            payload_budget_bytes=payload_budget_bytes,
        )


def _preview_project(
    target: ProjectTarget,
    owner: AgentOwnerIdentity,
    *,
    state_limit: int,
    state_after: str | None,
    inventory_loader: InventoryLoader,
    work_budget_seconds: float,
) -> StateRepairReport:
    mode = "preview"
    deadline = time.monotonic() + max(work_budget_seconds, 0.0)
    try:
        rows, snapshots, failed, bad_hoods, diagnostics = collect_published_rows(
            target.sidecar_path, target, owner
        )
    except Exception as exc:  # noqa: BLE001 - preview never raises
        return StateRepairReport(
            target.project_key,
            target.project,
            mode,
            error=f"state repair failed: {exc}",
        )
    selected, next_cursor, pass_complete, select_error = select_window(
        target, owner, state_limit, state_after, rows
    )
    if select_error is not None:
        return StateRepairReport(
            target.project_key,
            target.project,
            mode,
            failed=len(rows),
            diagnostics=(*diagnostics, select_error),
            error=select_error,
        )
    window = tuple(StateRepairWindowRow(hood, run_id) for hood, run_id in selected)
    if not selected:
        return StateRepairReport(
            target.project_key,
            target.project,
            mode,
            examined=0,
            next_cursor=next_cursor,
            pass_complete=pass_complete,
            diagnostics=tuple(diagnostics),
        )
    hoods = frozenset(hood for hood, _run_id in selected)
    try:
        inventory = inventory_loader(target, AgentIdentitySnapshot(owner), hoods)
    except Exception as exc:  # noqa: BLE001 - evidence failure is a diagnostic
        return StateRepairReport(
            target.project_key,
            target.project,
            mode,
            examined=len(selected),
            failed=len(selected),
            window=window,
            next_cursor=None,
            pass_complete=False,
            diagnostics=(*diagnostics, f"could not load local evidence: {exc}"),
        )
    resolved = resolve_selected(
        target,
        owner,
        snapshots,
        inventory,
        selected,
        deadline,
    )
    return StateRepairReport(
        target.project_key,
        target.project,
        mode,
        examined=len(selected),
        changed=len(resolved.changed),
        already_current=resolved.already_current,
        live=resolved.live,
        unresolved=resolved.unresolved,
        withheld=0,
        failed=failed + resolved.failed,
        affected=tuple(resolved.changed.values()),
        window=window,
        next_cursor=next_cursor,
        pass_complete=pass_complete,
        diagnostics=(*diagnostics, *resolved.diagnostics),
    )


def _apply_project_locked(
    target: ProjectTarget,
    owner: AgentOwnerIdentity,
    *,
    state_limit: int,
    state_after: str | None,
    git_runner: GitRunner,
    inventory_loader: InventoryLoader,
    work_budget_seconds: float,
    payload_budget_bytes: int,
) -> StateRepairReport:
    from sase.agents_sync.git_sync_ops import (
        abort_agents_rebase,
        clean_agents_payload_worktree,
        pull_agents_rebase,
    )

    mode = "apply"
    deadline = time.monotonic() + max(work_budget_seconds, 0.0)
    repo = target.sidecar_path
    cleanup_error = clean_agents_payload_worktree(repo, git_runner)
    if cleanup_error is not None:
        return StateRepairReport(
            target.project_key, target.project, mode, error=cleanup_error
        )
    pulled = pull_agents_rebase(repo, git_runner, "agents_state_repair.pull")
    if pulled.returncode != 0:
        from sase.agents_sync.git_sync_ops import agents_git_error

        cleanup = abort_agents_rebase(repo, git_runner)
        return StateRepairReport(
            target.project_key,
            target.project,
            mode,
            error=agents_git_error("git pull --rebase failed", pulled, cleanup),
        )
    report = plan_and_push_repair(
        target,
        owner,
        state_limit=state_limit,
        state_after=state_after,
        git_runner=git_runner,
        inventory_loader=inventory_loader,
        deadline=deadline,
        payload_budget_bytes=payload_budget_bytes,
        push_op="agents_state_repair.push",
        allow_retry=True,
    )
    cleanup_error = clean_agents_payload_worktree(repo, git_runner)
    if cleanup_error is not None and report.error is None:
        return StateRepairReport(
            target.project_key,
            target.project,
            mode,
            examined=report.examined,
            changed=report.changed,
            already_current=report.already_current,
            live=report.live,
            unresolved=report.unresolved,
            withheld=report.withheld,
            failed=report.failed,
            affected=report.affected,
            window=report.window,
            next_cursor=report.next_cursor,
            pass_complete=report.pass_complete,
            committed=report.committed,
            pushed=report.pushed,
            push_attempts=report.push_attempts,
            error=cleanup_error,
            diagnostics=report.diagnostics,
        )
    return report
