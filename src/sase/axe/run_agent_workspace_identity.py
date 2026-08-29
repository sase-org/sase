"""Runner workspace identity rebinding for VCS setup steps."""

from __future__ import annotations

import os
from collections.abc import Mapping
from typing import Any

from sase.axe.run_agent_exec_types import AgentExecContext
from sase.env_contracts import (
    SASE_ACTIVE_PROJECT_DIR_ENV,
    SASE_AGENT_WORKSPACE_NUM_ENV,
)
from sase.xprompt.workflow_executor_utils import (
    runner_bound_workspace_from_output,
    workspace_num_from_output,
)


def rebind_agent_workspace_identity_from_output(
    ctx: AgentExecContext,
    *,
    artifacts_dir: str,
    output: Mapping[str, Any],
    workspace_dir: str,
) -> None:
    """Adopt a VCS setup workspace when its output explicitly asks for it."""
    if not runner_bound_workspace_from_output(output):
        return

    workspace_num = workspace_num_from_output(output)
    if workspace_num is None:
        raise RuntimeError("runner-bound workspace output omitted workspace_num")

    _rebind_agent_workspace_identity(
        ctx,
        artifacts_dir=artifacts_dir,
        workspace_dir=workspace_dir,
        workspace_num=workspace_num,
    )


def _rebind_agent_workspace_identity(
    ctx: AgentExecContext,
    *,
    artifacts_dir: str,
    workspace_dir: str,
    workspace_num: int,
) -> None:
    """Move a placeholder-bound runner onto its VCS-allocated workspace."""
    if ctx.is_home_mode or workspace_num <= 0:
        return
    old_workspace_num = ctx.workspace_num
    if old_workspace_num not in (0, workspace_num):
        return

    workspace_dir = os.path.abspath(os.path.expanduser(workspace_dir))
    if old_workspace_num == 0:
        _transfer_workspace_claim_to_runner(ctx, workspace_num)

    ctx.workspace_num = workspace_num
    ctx.workspace_dir = workspace_dir
    _publish_workspace_env(workspace_dir=workspace_dir, workspace_num=workspace_num)
    _persist_agent_meta(ctx, artifacts_dir)
    if artifacts_dir != ctx.artifacts_dir:
        _persist_agent_meta(ctx, ctx.artifacts_dir)
    _write_occupant_record(ctx)

    if old_workspace_num == 0:
        _release_placeholder_claim(ctx)


def _transfer_workspace_claim_to_runner(
    ctx: AgentExecContext,
    workspace_num: int,
) -> None:
    from sase.running_field import transfer_workspace_claim

    result = transfer_workspace_claim(
        ctx.project_file,
        workspace_num,
        from_pid=os.getpid(),
        to_pid=os.getpid(),
        new_workflow=ctx.workflow_name,
        new_artifacts_timestamp=ctx.artifacts_timestamp,
        cl_name=ctx.cl_name,
        caller_tag="agent-workspace-rebind",
    )
    if not result.success:
        raise RuntimeError(
            f"Failed to rebind workspace #{workspace_num} to runner: "
            f"{result.error or 'unknown reason'}"
        )


def _publish_workspace_env(*, workspace_dir: str, workspace_num: int) -> None:
    os.environ[SASE_ACTIVE_PROJECT_DIR_ENV] = workspace_dir
    os.environ[SASE_AGENT_WORKSPACE_NUM_ENV] = str(workspace_num)

    from sase.sdd.env import set_sdd_dir_env

    set_sdd_dir_env(
        os.environ,
        workspace_dir=workspace_dir,
        workspace_num=workspace_num,
    )


def _persist_agent_meta(ctx: AgentExecContext, artifacts_dir: str) -> None:
    from sase.axe.run_agent_runner_setup import (
        refresh_linked_repos_for_workspace,
        write_agent_meta,
    )

    ctx.agent_meta["workspace_dir"] = ctx.workspace_dir
    ctx.agent_meta["workspace_num"] = ctx.workspace_num
    ctx.agent_meta["patch_name"] = ctx.cl_name
    ctx.agent_meta["changespec_name"] = ctx.cl_name
    ctx.agent_meta["cl_name"] = ctx.cl_name
    try:
        refresh_linked_repos_for_workspace(
            project_file=ctx.project_file,
            workspace_dir=ctx.workspace_dir,
            workspace_num=ctx.workspace_num,
            artifacts_dir=artifacts_dir,
            agent_meta=ctx.agent_meta,
        )
    except Exception:
        write_agent_meta(artifacts_dir, ctx.agent_meta)
        raise


def _write_occupant_record(ctx: AgentExecContext) -> None:
    if ctx.workspace_num <= 1:
        return

    from sase.workspace_provider.occupant import (
        new_occupant_record,
        write_occupant_record,
    )

    write_occupant_record(
        ctx.workspace_dir,
        new_occupant_record(
            pid=os.getpid(),
            workflow=ctx.workflow_name,
            project=ctx.project_name,
            workspace_num=ctx.workspace_num,
            artifacts_timestamp=ctx.artifacts_timestamp,
            agent_name=ctx.agent_name,
            cl_name=ctx.cl_name,
        ),
    )


def _release_placeholder_claim(ctx: AgentExecContext) -> None:
    from sase.running_field import release_workspace

    result = release_workspace(
        ctx.project_file,
        0,
        ctx.workflow_name,
        ctx.cl_name,
        caller_tag="agent-workspace-rebind-placeholder-release",
    )
    if not result.success:
        raise RuntimeError(
            f"Failed to release placeholder workspace #0 after rebind: "
            f"{result.error or 'unknown reason'}"
        )


__all__ = [
    "rebind_agent_workspace_identity_from_output",
]
