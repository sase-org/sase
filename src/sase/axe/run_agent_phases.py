"""Compatibility facade for agent runner lifecycle phase helpers.

The implementation is split across focused ``run_agent_*`` modules while this
module keeps the historical import and patch surface used by callers/tests.
"""

import os
import sys

from sase.axe.run_agent_directives import (
    AgentInfo,
    ClanSummaryResolutionRequest,
    extract_directives_and_write_meta,
)
from sase.axe.run_agent_markers import (
    build_done_marker,
    persist_refreshed_clan_summary,
    record_run_started_at,
    record_stop_time,
    write_agent_meta,
)
from sase.axe.run_agent_refs import (
    resolve_agent_refs_in_prompt,
    resolve_wait_chat_paths,
)
from sase.axe.run_agent_wait import (
    remaining_until,
    wait_for_dependencies,
)
from sase.axe.run_agent_wait_slots import wait_for_runner_slot


def claim_deferred_workspace(
    project_file: str,
    project_name: str,
    workflow_name: str,
    cl_name: str,
    artifacts_timestamp: str,
) -> tuple[int, str]:
    """Allocate a real workspace after deferred workspace wait completes.

    Releases the placeholder workspace_num=0 claim, allocates a new
    workspace, sets pre-allocation env vars, and claims the workspace.

    Returns (workspace_num, workspace_dir).
    """
    from sase.agent.launch_executor import workspace_allocation_attempt_limit
    from sase.running_field import (
        claim_workspace as claim_ws,
        get_first_available_axe_workspace,
        get_workspace_directory_for_num,
        release_workspace,
    )

    # Release the placeholder workspace_num=0 claim.
    release_workspace(project_file, 0, workflow_name, cl_name)

    vcs_wf_type = os.environ.get("SASE_AGENT_VCS_WORKFLOW_TYPE")
    prefix = None
    ws_get_dir = None
    if vcs_wf_type:
        from sase.workspace_provider import get_pre_allocated_env_prefix
        from sase.workspace_provider import get_workspace_directory as _ws_get_dir

        prefix = get_pre_allocated_env_prefix(vcs_wf_type)
        ws_get_dir = _ws_get_dir

    max_attempts = workspace_allocation_attempt_limit()
    last_error: BaseException | None = None
    workspace_num = 0
    workspace_dir = ""
    target_workspace_num = _deferred_target_workspace_num()
    target_workspace_dir = os.environ.get("SASE_AGENT_DEFERRED_TARGET_WORKSPACE_DIR")
    for _attempt in range(1, max_attempts + 1):
        try:
            workspace_num = target_workspace_num or get_first_available_axe_workspace(
                project_file
            )
            if vcs_wf_type:
                assert ws_get_dir is not None
                workspace_dir = ws_get_dir(
                    vcs_wf_type,
                    workspace_num,
                    project_name,
                    os.getcwd(),
                )
            else:
                workspace_dir = (
                    target_workspace_dir
                    if target_workspace_num and target_workspace_dir
                    else get_workspace_directory_for_num(workspace_num, project_name)[0]
                )

            claim_result = claim_ws(
                project_file,
                workspace_num,
                workflow_name,
                os.getpid(),
                cl_name,
                artifacts_timestamp=artifacts_timestamp,
            )
            if claim_result.success:
                if prefix:
                    os.environ[f"{prefix}_PRE_ALLOCATED"] = "1"
                    os.environ[f"{prefix}_WORKSPACE_NUM"] = str(workspace_num)
                    os.environ[f"{prefix}_WORKSPACE_DIR"] = workspace_dir
                break
            last_error = RuntimeError(
                f"Failed to claim workspace #{workspace_num}: "
                f"{claim_result.error or 'unknown reason'}"
            )
        except RuntimeError as exc:
            last_error = exc
            workspace_num = 0
            workspace_dir = ""
            break
    else:
        workspace_num = 0
        workspace_dir = ""

    if not workspace_dir or workspace_num == 0:
        print(
            "Failed to claim a real workspace after dependencies completed "
            f"for {project_name}/{cl_name} after {max_attempts} attempts; "
            "axe workspaces may all be claimed or racing with other launches."
            + (f" Last error: {last_error}" if last_error else ""),
            file=sys.stderr,
        )
        sys.exit(1)

    os.chdir(workspace_dir)
    os.environ["SASE_ACTIVE_PROJECT_DIR"] = workspace_dir
    from sase.sdd.env import set_sdd_dir_env

    set_sdd_dir_env(
        os.environ,
        workspace_dir=workspace_dir,
        workspace_num=workspace_num,
    )
    from sase.linked_repos import (
        apply_linked_repo_env,
        resolve_linked_repos_for_project,
    )

    apply_linked_repo_env(
        os.environ,
        resolve_linked_repos_for_project(
            project_file=project_file,
            workspace_dir=workspace_dir,
            workspace_num=workspace_num,
            materialize=False,
        ),
    )
    print(f"Claimed workspace #{workspace_num}: {workspace_dir}")
    return workspace_num, workspace_dir


def _deferred_target_workspace_num() -> int | None:
    raw_value = os.environ.get("SASE_AGENT_DEFERRED_TARGET_WORKSPACE_NUM")
    if not raw_value:
        return None
    try:
        value = int(raw_value)
    except ValueError:
        return None
    return value if value > 0 else None


__all__ = [
    "AgentInfo",
    "ClanSummaryResolutionRequest",
    "build_done_marker",
    "claim_deferred_workspace",
    "extract_directives_and_write_meta",
    "remaining_until",
    "persist_refreshed_clan_summary",
    "record_run_started_at",
    "record_stop_time",
    "resolve_agent_refs_in_prompt",
    "resolve_wait_chat_paths",
    "wait_for_dependencies",
    "wait_for_runner_slot",
    "write_agent_meta",
]
