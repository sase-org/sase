"""SDD and epic support for accepted execution plans."""

from __future__ import annotations

import logging
import shlex
from collections.abc import Callable
from pathlib import Path
from typing import TYPE_CHECKING, Any

from sase.bead.epic_launch import build_epic_launch_argv
from sase.sdd.plan_refs import PLAN_REFERENCE_PREFIX

if TYPE_CHECKING:
    from sase.axe.run_agent_exec import AgentExecContext, LoopState

logger = logging.getLogger(__name__)


def publish_planner_prompt_archive(
    ctx: AgentExecContext,
    state: LoopState,
    *,
    agent_name: str,
    prompt_content: str,
    plan_name: str,
    yyyymm: str,
) -> Path | None:
    """Publish the approved planner prompt to the canonical agents sidecar."""
    from sase.agents_sync.git import run_git
    from sase.agents_sync.prompt_archive import publish_prompt_archive

    revision_result = run_git(
        Path(ctx.workspace_dir),
        ["rev-parse", "HEAD"],
        op="prompt_archive.planner_revision",
    )
    primary_revision = revision_result.stdout.strip()
    if revision_result.returncode != 0 or not primary_revision:
        logger.warning(
            "Planner prompt archive publication skipped: primary revision unavailable"
        )
        return None
    outcome = publish_prompt_archive(
        agent_name,
        primary_revision,
        project=ctx.project_name,
        commit_cwd=ctx.workspace_dir,
        agent_artifacts_dir=state.current_artifacts_dir,
        prompt_content=prompt_content,
        plan_ref=f"{PLAN_REFERENCE_PREFIX}{yyyymm}/{plan_name}.md",
        prompt_name=plan_name,
        yyyymm=yyyymm,
    )
    if outcome.error or outcome.skip_reason:
        logger.warning(
            "Planner prompt archive publication deferred: %s",
            outcome.error or outcome.skip_reason,
        )
    return outcome.prompt_path


def accepted_plan_action_for_meta(plan_result: Any) -> str:
    """Return the normalized accepted-plan action stored in agent metadata."""
    if plan_result.action == "approve" and not plan_result.run_coder:
        return "commit"
    if (
        plan_result.action == "approve"
        and plan_result.commit_plan
        and plan_result.run_coder
    ):
        return "tale"
    return str(plan_result.action)


def notify_epic_launch_failure(
    ctx: AgentExecContext,
    plan_file: str,
    output_tail: tuple[str, ...],
) -> None:
    """Send a best-effort error notification with a direct resume command."""
    argv = build_epic_launch_argv(plan_file)
    resume_command = shlex.join(argv)
    notes = [
        f"Epic launch failed for {Path(plan_file).name}",
        f"Resume with: {resume_command}",
    ]
    if output_tail:
        notes.append(f"Last output: {output_tail[-1]}")
    try:
        from sase.notifications.senders import notify_workflow_complete

        notify_workflow_complete(
            sender="user-agent",
            cl_name=ctx.cl_name,
            success=False,
            notes=notes,
            action="ViewErrorReport",
            action_data={
                "error_report_path": ctx.output_path,
                "patch_name": ctx.cl_name,
                "cl_name": ctx.cl_name,
                **({"agent_name": ctx.agent_name} if ctx.agent_name else {}),
            },
            extra_files=[ctx.output_path] if Path(ctx.output_path).is_file() else None,
        )
    except Exception:
        logger.warning("Failed to send epic-launch error notification", exc_info=True)


def epic_launch_is_host_owned(plan_result: Any) -> bool:
    """Return whether the approval response handed the epic launch to the host."""
    return (
        plan_result.action == "epic"
        and getattr(plan_result, "epic_launch_owner", None) == "host"
    )


def record_epic_store_failure(
    plan_result: Any,
    ctx: AgentExecContext,
    state: LoopState,
    store_unusable_error: str,
    *,
    update_meta: Callable[[str, str, Any], None],
    notify_failure: Callable[[AgentExecContext, str, tuple[str, ...]], None],
    log: logging.Logger,
) -> str | None:
    """Record an epic SDD store failure and return the loop outcome, if any.

    A host-owned launch continues independently when planner-side SDD
    publication fails. A planner-owned launch instead reports a launch failure.
    """
    if epic_launch_is_host_owned(plan_result):
        update_meta(
            state.current_artifacts_dir,
            "sdd_publication_error",
            store_unusable_error,
        )
        log.warning(
            "Approved epic SDD publication failed (%s); the host-owned epic "
            "launch continues independently",
            store_unusable_error,
        )
        return None
    update_meta(
        state.current_artifacts_dir,
        "epic_launch_error",
        store_unusable_error,
    )
    notify_failure(ctx, plan_result.plan_file, (store_unusable_error,))
    return "epic_launch_failed"


def store_failure_detail(exc: Exception) -> str:
    """Describe an epic SDD store failure, naming a mid-run code swap if any."""
    from sase.axe.source_skew import code_swap_explanation

    detail = str(exc) or type(exc).__name__
    swap = code_swap_explanation(exc)
    if swap is None:
        return detail
    return f"mid-run sase code swap, not an unusable store: {detail} -- {swap}"


def require_usable_sdd_store(repo_root: Path) -> None:
    """Validate a materialized SDD repository before any accepted-plan write."""
    if not (repo_root / ".git").exists():
        return
    from sase.sdd._git_contention import store_git_write_lock
    from sase.sdd._repository_transaction import (
        SddRepositoryHealthError,
        require_sdd_repository_health,
    )

    with store_git_write_lock(
        repo_root,
        op="axe.accepted_plan_preflight",
        mutates_worktree=True,
    ) as acquired:
        if not acquired:
            raise SddRepositoryHealthError(
                f"SDD repository {repo_root.resolve()} could not acquire its store "
                "write lock; the approved plan was not copied"
            )
        require_sdd_repository_health(repo_root)
