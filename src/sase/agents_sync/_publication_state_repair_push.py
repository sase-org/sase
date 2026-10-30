"""Apply resolved repair plans and push their sidecar changes."""

from __future__ import annotations

import time
from collections.abc import Callable

from sase.agents_sync.io import AgentsSyncFormatError
from sase.agents_sync.v2_io import apply_payload_batched_atomic
from sase.agents_sync.git import GitRunner
from sase.agents_sync.models import ProjectTarget
from sase.core.agent_identity_facade import AgentIdentitySnapshot, AgentOwnerIdentity
from sase.agents_sync._publication_state_repair_evidence import (
    collect_published_rows,
    resolve_selected,
    select_window,
)
from sase.agents_sync._publication_state_repair_payload import (
    plan_state_payload,
    protection_scope,
)
from sase.agents_sync._publication_state_repair_retry import retry_divergent_repair
from sase.agents_sync._publication_state_repair_types import (
    InventoryLoader,
    StateRepairReport,
    StateRepairWindowRow,
)


def _push_ahead_convergence(
    target: ProjectTarget,
    git_runner: GitRunner,
    push_op: str,
) -> tuple[bool, str | None, int]:
    """Push unpushed repair commits on a verified no-write window.

    A failed push leaves this window's commit ahead of the remote; the retry
    after remediation lands here with nothing left to write, so the owed push
    is attempted to converge the remote. Returns ``(pushed, error, attempts)``;
    an error freezes the cursor exactly like a failed repair push.
    """

    from sase.agents_sync.git_sync_ops import agents_ahead_count

    try:
        ahead = agents_ahead_count(target.sidecar_path, git_runner)
    except Exception:  # noqa: BLE001 - no push without a readable count.
        return False, None, 0
    if ahead <= 0:
        return False, None, 0
    pushed = git_runner(target.sidecar_path, ["push"], network=True, op=push_op)
    if pushed.returncode == 0:
        return True, None, 1
    from sase.agents_sync.publication_recovery import (
        recover_publication_push,
        sanitized_push_error,
    )

    recovery = recover_publication_push(
        target.sidecar_path,
        git_runner,
        project_key=target.project_key,
        repository_identity=target.remote_url,
        returncode=pushed.returncode,
        stdout=pushed.stdout or "",
        stderr=pushed.stderr or "",
    )
    return (
        False,
        sanitized_push_error(
            "git push failed",
            recovery.rejection,
            blocked_paths=recovery.blocked_paths,
        ),
        1,
    )


def plan_and_push_repair(
    target: ProjectTarget,
    owner: AgentOwnerIdentity,
    *,
    state_limit: int,
    state_after: str | None,
    git_runner: GitRunner,
    inventory_loader: InventoryLoader,
    deadline: float,
    payload_budget_bytes: int,
    push_op: str,
    allow_retry: bool,
) -> StateRepairReport:
    from sase.agents_sync.git_sync_ops import (
        abort_agents_rebase,
        agents_ahead_count,
        agents_git_error,
        clean_agents_payload_worktree,
        commit_agents_payload_if_dirty,
        is_agents_non_fast_forward,
        pull_agents_rebase,
    )

    mode = "apply"
    try:
        rows, snapshots, collect_failed, bad_hoods, collect_diagnostics = (
            collect_published_rows(target.sidecar_path, target, owner)
        )
    except Exception as exc:  # noqa: BLE001 - per-project isolation
        return StateRepairReport(
            target.project_key,
            target.project,
            mode,
            error=f"state repair failed: {exc}",
        )
    selected, next_cursor, pass_complete, select_error = select_window(
        target, owner, state_limit, state_after, rows
    )
    window = tuple(StateRepairWindowRow(hood, run_id) for hood, run_id in selected)
    if select_error is not None:
        return StateRepairReport(
            target.project_key,
            target.project,
            mode,
            failed=len(rows),
            diagnostics=(*collect_diagnostics, select_error),
            error=select_error,
        )
    if not selected:
        return StateRepairReport(
            target.project_key,
            target.project,
            mode,
            examined=0,
            next_cursor=next_cursor,
            pass_complete=pass_complete,
            diagnostics=tuple(collect_diagnostics),
        )
    hoods = frozenset(row[0] for row in selected)
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
            diagnostics=(
                *collect_diagnostics,
                f"could not load local evidence: {exc}",
            ),
        )
    resolved = resolve_selected(target, owner, snapshots, inventory, selected, deadline)
    if not resolved.changed:
        # Verified no-write window: the published snapshot already matches
        # local evidence. A previous attempt's unpushed repair commit still
        # converges here so a retry after remediation completes remotely.
        ahead_pushed, push_error, push_attempts = _push_ahead_convergence(
            target, git_runner, "agents_state_repair.push_ahead"
        )
        if push_error is not None:
            return StateRepairReport(
                target.project_key,
                target.project,
                mode,
                examined=len(selected),
                changed=0,
                already_current=resolved.already_current,
                live=resolved.live,
                unresolved=resolved.unresolved,
                withheld=0,
                failed=collect_failed + resolved.failed,
                affected=(),
                window=window,
                next_cursor=None,
                pass_complete=False,
                push_attempts=push_attempts,
                error=push_error,
                diagnostics=(*collect_diagnostics, *resolved.diagnostics),
            )
        return StateRepairReport(
            target.project_key,
            target.project,
            mode,
            examined=len(selected),
            changed=0,
            already_current=resolved.already_current,
            live=resolved.live,
            unresolved=resolved.unresolved,
            withheld=0,
            failed=collect_failed + resolved.failed,
            affected=(),
            window=window,
            next_cursor=next_cursor,
            pass_complete=pass_complete,
            pushed=ahead_pushed,
            push_attempts=push_attempts,
            diagnostics=(*collect_diagnostics, *resolved.diagnostics),
        )
    payload, updated, withheld, withheld_diags, plan_failed, plan_diags = (
        plan_state_payload(
            target,
            owner,
            resolved,
            deadline,
            bad_hoods=bad_hoods,
        )
    )
    failed = collect_failed + resolved.failed + plan_failed
    diagnostics = (*collect_diagnostics, *resolved.diagnostics, *plan_diags)
    if not payload and not updated:
        # Every changed row was withheld or failed: nothing to publish, and
        # the cursor must not advance past unrepaired rows.
        return StateRepairReport(
            target.project_key,
            target.project,
            mode,
            examined=len(selected),
            changed=0,
            already_current=resolved.already_current,
            live=resolved.live,
            unresolved=resolved.unresolved,
            withheld=withheld,
            failed=failed,
            affected=(),
            window=window,
            next_cursor=None,
            pass_complete=False,
            diagnostics=(*diagnostics, *withheld_diags),
        )
    total_bytes = sum(len(value) for value in payload.values())
    if total_bytes > payload_budget_bytes:
        return StateRepairReport(
            target.project_key,
            target.project,
            mode,
            examined=len(selected),
            changed=0,
            already_current=resolved.already_current,
            live=resolved.live,
            unresolved=resolved.unresolved,
            withheld=withheld,
            failed=failed + len(updated),
            affected=(),
            window=window,
            next_cursor=None,
            pass_complete=False,
            diagnostics=(
                *diagnostics,
                *withheld_diags,
                f"state repair payload of {total_bytes} bytes exceeds the "
                f"{payload_budget_bytes} byte limit; retry with a smaller limit",
            ),
        )
    try:
        wrote = apply_payload_batched_atomic(
            target.sidecar_path, payload, batch_budget_bytes=payload_budget_bytes
        )
    except (AgentsSyncFormatError, OSError, RuntimeError, ValueError) as exc:
        clean_agents_payload_worktree(target.sidecar_path, git_runner)
        return StateRepairReport(
            target.project_key,
            target.project,
            mode,
            examined=len(selected),
            changed=0,
            already_current=resolved.already_current,
            live=resolved.live,
            unresolved=resolved.unresolved,
            withheld=withheld,
            failed=failed + len(updated),
            affected=(),
            window=window,
            next_cursor=None,
            pass_complete=False,
            diagnostics=(
                *diagnostics,
                *withheld_diags,
                f"state repair failed: {exc}",
            ),
        )
    if not wrote:
        ahead_pushed, push_error, ahead_attempts = _push_ahead_convergence(
            target, git_runner, "agents_state_repair.push_ahead"
        )
        if push_error is not None:
            return StateRepairReport(
                target.project_key,
                target.project,
                mode,
                examined=len(selected),
                changed=0,
                already_current=resolved.already_current,
                live=resolved.live,
                unresolved=resolved.unresolved,
                withheld=withheld,
                failed=failed,
                affected=(),
                window=window,
                next_cursor=None,
                pass_complete=False,
                push_attempts=ahead_attempts,
                error=push_error,
                diagnostics=(*diagnostics, *withheld_diags),
            )
        return StateRepairReport(
            target.project_key,
            target.project,
            mode,
            examined=len(selected),
            changed=0,
            already_current=resolved.already_current + len(resolved.changed),
            live=resolved.live,
            unresolved=resolved.unresolved,
            withheld=withheld,
            failed=failed,
            affected=(),
            window=window,
            next_cursor=next_cursor,
            pass_complete=pass_complete,
            pushed=ahead_pushed,
            push_attempts=ahead_attempts,
            diagnostics=(*diagnostics, *withheld_diags),
        )
    scope = protection_scope(target)
    committed = commit_agents_payload_if_dirty(
        target.sidecar_path, owner, git_runner, protection_scope=scope
    )
    if isinstance(committed, str):
        clean_agents_payload_worktree(target.sidecar_path, git_runner)
        return StateRepairReport(
            target.project_key,
            target.project,
            mode,
            examined=len(selected),
            changed=0,
            already_current=resolved.already_current,
            live=resolved.live,
            unresolved=resolved.unresolved,
            withheld=withheld,
            failed=failed + len(updated),
            affected=(),
            window=window,
            next_cursor=None,
            pass_complete=False,
            error=committed,
            diagnostics=(*diagnostics, *withheld_diags),
        )
    if not committed:
        no_change = len(resolved.changed) - withheld
        return StateRepairReport(
            target.project_key,
            target.project,
            mode,
            examined=len(selected),
            changed=0,
            already_current=resolved.already_current + max(no_change, 0),
            live=resolved.live,
            unresolved=resolved.unresolved,
            withheld=withheld,
            failed=failed,
            affected=(),
            window=window,
            next_cursor=next_cursor,
            pass_complete=pass_complete,
            diagnostics=(*diagnostics, *withheld_diags),
        )
    should_push = committed or agents_ahead_count(target.sidecar_path, git_runner) > 0
    if not should_push:  # pragma: no cover - commit implies push
        return StateRepairReport(
            target.project_key,
            target.project,
            mode,
            examined=len(selected),
            changed=len(updated),
            already_current=resolved.already_current,
            live=resolved.live,
            unresolved=resolved.unresolved,
            withheld=withheld,
            failed=failed,
            affected=tuple(resolved.changed.values()),
            window=window,
            next_cursor=next_cursor,
            pass_complete=pass_complete,
            committed=True,
            diagnostics=(*diagnostics, *withheld_diags),
        )
    pushed = git_runner(target.sidecar_path, ["push"], network=True, op=push_op)
    if pushed.returncode == 0:
        return StateRepairReport(
            target.project_key,
            target.project,
            mode,
            examined=len(selected),
            changed=len(updated),
            already_current=resolved.already_current,
            live=resolved.live,
            unresolved=resolved.unresolved,
            withheld=withheld,
            failed=failed,
            affected=tuple(
                item for key, item in resolved.changed.items() if key in updated
            ),
            window=window,
            next_cursor=next_cursor,
            pass_complete=pass_complete,
            committed=True,
            pushed=True,
            push_attempts=1,
            diagnostics=(*diagnostics, *withheld_diags),
        )
    from sase.agents_sync.publication_recovery import (
        RECOVERY_RETRY_DIVERGENCE,
        recover_publication_push,
    )

    recovery = recover_publication_push(
        target.sidecar_path,
        git_runner,
        project_key=target.project_key,
        repository_identity=target.remote_url,
        returncode=pushed.returncode,
        stdout=pushed.stdout or "",
        stderr=pushed.stderr or "",
    )
    if (
        allow_retry
        and recovery.action == RECOVERY_RETRY_DIVERGENCE
        and is_agents_non_fast_forward(pushed)
    ):
        retry_base = StateRepairReport(
            target.project_key,
            target.project,
            mode,
            examined=len(selected),
            changed=0,
            already_current=resolved.already_current,
            live=resolved.live,
            unresolved=resolved.unresolved,
            withheld=withheld,
            failed=failed + len(updated),
            affected=(),
            window=window,
            next_cursor=None,
            pass_complete=False,
            push_attempts=1,
            diagnostics=(*diagnostics, *withheld_diags),
        )
        return retry_divergent_repair(
            target,
            git_runner,
            retry_base,
            lambda: plan_and_push_repair(
                target,
                owner,
                state_limit=state_limit,
                state_after=state_after,
                git_runner=git_runner,
                inventory_loader=inventory_loader,
                deadline=deadline,
                payload_budget_bytes=payload_budget_bytes,
                push_op="agents_state_repair.retry_push",
                allow_retry=False,
            ),
        )
    from sase.agents_sync.publication_recovery import sanitized_push_error

    message = sanitized_push_error(
        "git push failed",
        recovery.rejection,
        blocked_paths=recovery.blocked_paths,
    )
    return StateRepairReport(
        target.project_key,
        target.project,
        mode,
        examined=len(selected),
        changed=0,
        already_current=resolved.already_current,
        live=resolved.live,
        unresolved=resolved.unresolved,
        withheld=withheld,
        failed=failed + len(updated),
        affected=(),
        window=window,
        next_cursor=None,
        pass_complete=False,
        push_attempts=1,
        error=message,
        diagnostics=(*diagnostics, *withheld_diags),
    )
