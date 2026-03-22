"""Setup step for the #git xprompt workflow."""

import os

from sase.workspace_provider.utils import ensure_git_clone
from sase.workspace_provider.plugins.bare_git_workspace import resolve_git_ref
from sase.running_field import (
    claim_next_axe_workspace,
    claim_workspace,
)


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

    pid = os.getpid()
    workflow_name = workflow_label or f"git-{git_ref}"

    # Check if workspace was pre-allocated by the TUI
    pre_allocated = os.environ.get("SASE_GIT_PRE_ALLOCATED") == "1"
    if pre_allocated:
        workspace_num = int(os.environ["SASE_GIT_WORKSPACE_NUM"])
        workspace_dir = os.environ["SASE_GIT_WORKSPACE_DIR"]
    elif n is not None:
        workspace_num = n
        workspace_dir = ensure_git_clone(resolved.primary_workspace_dir, workspace_num)
        claim_workspace(
            project_file,
            workspace_num,
            workflow_name,
            pid,
            None,
            pinned=not release,
        )
    else:
        # Atomically find + claim to prevent TOCTOU races where two
        # concurrent processes (e.g. mentors) both see the same workspace
        # as available and both claim it.
        workspace_num = claim_next_axe_workspace(
            project_file,
            workflow_name,
            pid,
            pinned=not release,
        )
        workspace_dir = ensure_git_clone(resolved.primary_workspace_dir, workspace_num)

    print(f"project_name={project_name}")
    print(f"project_file={project_file}")
    print(f"workspace_dir={workspace_dir}")
    print(f"workspace_num={workspace_num}")
    print(f"checkout_target={resolved.checkout_target}")
    print(f"primary_workspace_dir={resolved.primary_workspace_dir}")
    # Don't release pre-allocated workspaces — the launcher handles that
    should_release = release and not pre_allocated
    print(f"should_release={'true' if should_release else 'false'}")
    print(f"_chdir={workspace_dir}")
    print(f"meta_workspace={workspace_num}")
    print(f"workflow_name={workflow_name}")
