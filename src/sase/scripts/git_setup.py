"""Setup step for the #git xprompt workflow."""

import os

from sase.running_field import (
    WorkspaceClaimError,
    claim_next_axe_workspace,
    claim_workspace,
    find_runner_numbered_workspace,
    release_workspace,
    runner_has_placeholder_workspace,
)
from sase.sdd.store import materialize_sdd_store
from sase.workspace_provider.plugins.bare_git_workspace import resolve_git_ref
from sase.workspace_provider.utils import ensure_workspace_checkout

_CALLER_TAG = "git-setup"


def main(
    *,
    git_ref: str,
    n: int | None,
    release: bool,
    workflow_label: str | None = None,
) -> None:
    """Resolve git ref, claim a workspace, and print config.

    Prints key=value output for the workflow executor.
    """
    resolved = resolve_git_ref(git_ref)

    project_name = resolved.project_name
    project_file = resolved.project_file

    # Use the parent process PID, not our own.  This setup step runs as a
    # short-lived subprocess of the workflow runner, so ``os.getpid()`` dies
    # the moment setup returns: ``stale_running_cleanup`` would reap the
    # RUNNING row while the runner still holds the checkout, and the
    # identity-checked release step would refuse a row whose pid no longer
    # matches the runner.  ``#gh:`` setup claims the same way.
    pid = os.getppid()
    workflow_name = workflow_label or f"git-{git_ref}"
    cl_name = None if "/" in git_ref else git_ref
    runner_bound_workspace = False

    # Check if workspace was pre-allocated by the TUI
    pre_allocated = (
        os.environ.get("SASE_GIT_PRE_ALLOCATED") == "1"
        and "SASE_GIT_WORKSPACE_NUM" in os.environ
        and "SASE_GIT_WORKSPACE_DIR" in os.environ
    )
    if pre_allocated:
        workspace_num = int(os.environ["SASE_GIT_WORKSPACE_NUM"])
        workspace_dir = os.environ["SASE_GIT_WORKSPACE_DIR"]
    elif n is not None:
        workspace_num = n
        claim_result = claim_workspace(
            project_file,
            workspace_num,
            workflow_name,
            pid,
            cl_name,
            pinned=not release,
            caller_tag=_CALLER_TAG,
        )
        if not claim_result.success:
            raise WorkspaceClaimError(
                f"Failed to claim workspace #{workspace_num}: "
                f"{claim_result.error or 'unknown reason'}",
                workspace_num=workspace_num,
            )
        try:
            workspace_dir = ensure_workspace_checkout(
                resolved.primary_workspace_dir, workspace_num
            )
        except Exception:
            release_workspace(
                project_file,
                workspace_num,
                workflow_name,
                cl_name,
                caller_tag=_CALLER_TAG,
            )
            raise
    else:
        adopted = _adopt_runner_workspace(
            project_file=project_file,
            primary_workspace_dir=resolved.primary_workspace_dir,
        )
        if adopted is not None:
            # Runner already holds a numbered pool claim: reuse it the
            # same way the launcher pre-allocation branch does.
            workspace_num, workspace_dir = adopted
            pre_allocated = True
        else:
            runner_bound_workspace = runner_has_placeholder_workspace(
                project_file, pid=pid
            )
            # Atomically find + claim to prevent TOCTOU races where two
            # concurrent processes (e.g. mentors) both see the same workspace
            # as available and both claim it.
            workspace_num = claim_next_axe_workspace(
                project_file,
                workflow_name,
                pid,
                cl_name=cl_name,
                pinned=not release,
                caller_tag=_CALLER_TAG,
            )
            workspace_dir = ensure_workspace_checkout(
                resolved.primary_workspace_dir, workspace_num
            )

    print(f"project_name={project_name}")
    print(f"project_file={project_file}")
    print(f"workspace_dir={workspace_dir}")
    print(f"workspace_num={workspace_num}")
    print(f"checkout_target={resolved.checkout_target}")
    print(f"primary_workspace_dir={resolved.primary_workspace_dir}")
    # Don't release pre-allocated workspaces — the launcher handles that
    should_release = release and not pre_allocated and not runner_bound_workspace
    print(f"should_release={'true' if should_release else 'false'}")
    print(f"runner_bound_workspace={'true' if runner_bound_workspace else 'false'}")
    print(f"_chdir={workspace_dir}")
    print(f"meta_workspace={workspace_num}")
    print(f"workflow_name={workflow_name}")


def _adopt_runner_workspace(
    *,
    project_file: str,
    primary_workspace_dir: str,
) -> tuple[int, str] | None:
    """Reuse the calling runner's numbered pool claim, if it holds one."""
    workspace_num = find_runner_numbered_workspace(project_file)
    if workspace_num is None:
        return None
    workspace_dir = ensure_workspace_checkout(primary_workspace_dir, workspace_num)
    materialize_sdd_store(workspace_dir, workspace_num)
    return workspace_num, workspace_dir
