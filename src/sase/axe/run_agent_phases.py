"""Compatibility facade for agent runner lifecycle phase helpers.

The implementation is split across focused ``run_agent_*`` modules while this
module keeps the historical import and patch surface used by callers/tests.
"""

from collections.abc import Callable
import os
import sys

from sase.running_field import WorkspaceClaim

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

    Releases the placeholder workspace_num=0 claim, then atomically
    allocates-and-claims a workspace *before* materializing the checkout.
    A pinned family-attach target is a single-shot claim: an occupied
    checkout fails the run with the occupant named.

    Returns (workspace_num, workspace_dir).
    """
    from sase.agent.launch_executor import workspace_allocation_attempt_limit
    from sase.running_field import release_workspace

    # Release the placeholder workspace_num=0 claim.
    release_workspace(
        project_file,
        0,
        workflow_name,
        cl_name,
        caller_tag="deferred-placeholder-release",
    )

    vcs_wf_type = os.environ.get("SASE_AGENT_VCS_WORKFLOW_TYPE")
    prefix = None
    ws_get_dir = None
    if vcs_wf_type:
        from sase.workspace_provider import get_pre_allocated_env_prefix
        from sase.workspace_provider import get_workspace_directory as _ws_get_dir

        prefix = get_pre_allocated_env_prefix(vcs_wf_type)
        ws_get_dir = _ws_get_dir

    max_attempts = workspace_allocation_attempt_limit()
    target_workspace_num = _deferred_target_workspace_num()
    target_workspace_dir = os.environ.get("SASE_AGENT_DEFERRED_TARGET_WORKSPACE_DIR")
    if target_workspace_num is not None:
        workspace_num, workspace_dir, pinned_error = _claim_pinned_deferred_workspace(
            project_file=project_file,
            project_name=project_name,
            workflow_name=workflow_name,
            cl_name=cl_name,
            artifacts_timestamp=artifacts_timestamp,
            target_workspace_num=target_workspace_num,
            target_workspace_dir=target_workspace_dir,
            vcs_wf_type=vcs_wf_type,
            ws_get_dir=ws_get_dir,
        )
        if not workspace_dir or workspace_num == 0:
            print(
                pinned_error
                or (
                    f"Pinned workspace #{target_workspace_num} could not be "
                    f"claimed for {project_name}/{cl_name}."
                ),
                file=sys.stderr,
            )
            sys.exit(1)
    else:
        workspace_num, workspace_dir, last_error = _claim_next_deferred_workspace(
            project_file=project_file,
            project_name=project_name,
            workflow_name=workflow_name,
            cl_name=cl_name,
            artifacts_timestamp=artifacts_timestamp,
            max_attempts=max_attempts,
            vcs_wf_type=vcs_wf_type,
            ws_get_dir=ws_get_dir,
        )
        if not workspace_dir or workspace_num == 0:
            print(
                "Failed to claim a real workspace after dependencies completed "
                f"for {project_name}/{cl_name} after {max_attempts} attempts; "
                "axe workspaces may all be claimed or racing with other launches."
                + (f" Last error: {last_error}" if last_error else ""),
                file=sys.stderr,
            )
            sys.exit(1)

    if prefix:
        os.environ[f"{prefix}_PRE_ALLOCATED"] = "1"
        os.environ[f"{prefix}_WORKSPACE_NUM"] = str(workspace_num)
        os.environ[f"{prefix}_WORKSPACE_DIR"] = workspace_dir

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


def _claim_next_deferred_workspace(
    *,
    project_file: str,
    project_name: str,
    workflow_name: str,
    cl_name: str,
    artifacts_timestamp: str,
    max_attempts: int,
    vcs_wf_type: str | None,
    ws_get_dir: Callable[[str, int, str, str], str] | None,
) -> tuple[int, str, BaseException | None]:
    """Atomically allocate, then materialize; release the slot if materialize fails."""
    from sase.running_field import claim_next_axe_workspace, release_workspace

    last_error: BaseException | None = None
    for _attempt in range(1, max_attempts + 1):
        claimed_num = 0
        try:
            claimed_num = claim_next_axe_workspace(
                project_file,
                workflow_name,
                os.getpid(),
                cl_name,
                artifacts_timestamp=artifacts_timestamp,
                caller_tag="deferred-claim",
            )
            workspace_dir = _resolve_deferred_workspace_dir(
                workspace_num=claimed_num,
                project_name=project_name,
                vcs_wf_type=vcs_wf_type,
                ws_get_dir=ws_get_dir,
                target_workspace_num=None,
                target_workspace_dir=None,
            )
            return claimed_num, workspace_dir, None
        except Exception as exc:
            last_error = exc
            if claimed_num:
                release_workspace(
                    project_file,
                    claimed_num,
                    workflow_name,
                    cl_name,
                    caller_tag="deferred-claim",
                )
    return 0, "", last_error


def _claim_pinned_deferred_workspace(
    *,
    project_file: str,
    project_name: str,
    workflow_name: str,
    cl_name: str,
    artifacts_timestamp: str,
    target_workspace_num: int,
    target_workspace_dir: str | None,
    vcs_wf_type: str | None,
    ws_get_dir: Callable[[str, int, str, str], str] | None,
) -> tuple[int, str, str | None]:
    """Claim a family-attach pin once. Occupied checkouts fail with the occupant named."""
    from sase.running_field import claim_workspace, release_workspace

    claim_result = claim_workspace(
        project_file,
        target_workspace_num,
        workflow_name,
        os.getpid(),
        cl_name,
        artifacts_timestamp=artifacts_timestamp,
        caller_tag="deferred-claim",
    )
    if not claim_result.success:
        occupant = _describe_workspace_occupant(project_file, target_workspace_num)
        if occupant is not None:
            return (
                0,
                "",
                f"Pinned workspace #{target_workspace_num} is already claimed by "
                f"{occupant}",
            )
        return (
            0,
            "",
            f"Pinned workspace #{target_workspace_num} could not be claimed: "
            f"{claim_result.error or 'unknown reason'}",
        )

    try:
        workspace_dir = _resolve_deferred_workspace_dir(
            workspace_num=target_workspace_num,
            project_name=project_name,
            vcs_wf_type=vcs_wf_type,
            ws_get_dir=ws_get_dir,
            target_workspace_num=target_workspace_num,
            target_workspace_dir=target_workspace_dir,
        )
    except Exception as exc:
        release_workspace(
            project_file,
            target_workspace_num,
            workflow_name,
            cl_name,
            caller_tag="deferred-claim",
        )
        return (
            0,
            "",
            f"Pinned workspace #{target_workspace_num} was claimed but "
            f"failed to materialize: {exc}",
        )
    return target_workspace_num, workspace_dir, None


def _resolve_deferred_workspace_dir(
    *,
    workspace_num: int,
    project_name: str,
    vcs_wf_type: str | None,
    ws_get_dir: Callable[[str, int, str, str], str] | None,
    target_workspace_num: int | None,
    target_workspace_dir: str | None,
) -> str:
    from sase.running_field import get_workspace_directory_for_num

    if vcs_wf_type:
        if ws_get_dir is None:
            raise RuntimeError(
                f"VCS workflow type {vcs_wf_type!r} has no workspace directory resolver"
            )
        return ws_get_dir(
            vcs_wf_type,
            workspace_num,
            project_name,
            os.getcwd(),
        )
    if target_workspace_num and target_workspace_dir:
        return target_workspace_dir
    return get_workspace_directory_for_num(workspace_num, project_name)[0]


def _describe_workspace_occupant(project_file: str, workspace_num: int) -> str | None:
    from sase.running_field import get_claimed_workspaces

    occupants = [
        claim
        for claim in get_claimed_workspaces(project_file)
        if claim.workspace_num == workspace_num
    ]
    if not occupants:
        return None
    return "; ".join(_format_workspace_occupant(claim) for claim in occupants)


def _format_workspace_occupant(claim: WorkspaceClaim) -> str:
    name = claim.cl_name or claim.workflow
    liveness = "live" if _pid_is_alive(claim.pid) else "dead"
    detail = f"{name} (pid {claim.pid}, {liveness}, workflow {claim.workflow}"
    if claim.artifacts_timestamp:
        detail += f", artifacts {claim.artifacts_timestamp}"
    return detail + ")"


def _pid_is_alive(pid: int) -> bool:
    if pid <= 0:
        return False
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


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
