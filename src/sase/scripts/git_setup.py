"""Setup step for the #git xprompt workflow."""

import os

from sase.workspace_utils import ensure_git_clone
from sase.git_workspace import resolve_git_ref
from sase.running_field import (
    claim_workspace,
    get_first_available_axe_workspace,
)


def main(*, git_ref: str, n: int | None, release: bool) -> None:
    """Resolve git ref, claim a workspace, and print config.

    Prints key=value output for the workflow executor.
    """
    resolved = resolve_git_ref(git_ref)

    project_name = resolved.project_name
    project_file = resolved.project_file

    # Check if workspace was pre-allocated by the TUI
    if os.environ.get("SASE_GIT_PRE_ALLOCATED") == "1":
        workspace_num = int(os.environ["SASE_GIT_WORKSPACE_NUM"])
        workspace_dir = os.environ["SASE_GIT_WORKSPACE_DIR"]
    elif n is not None:
        workspace_num = n
        workspace_dir = ensure_git_clone(resolved.primary_workspace_dir, workspace_num)
    else:
        workspace_num = get_first_available_axe_workspace(project_file)
        workspace_dir = ensure_git_clone(resolved.primary_workspace_dir, workspace_num)

    pid = os.getpid()
    workflow_name = f"git-{git_ref}"
    claim_workspace(
        project_file,
        workspace_num,
        workflow_name,
        pid,
        None,
        pinned=not release,
    )

    print(f"project_name={project_name}")
    print(f"project_file={project_file}")
    print(f"workspace_dir={workspace_dir}")
    print(f"workspace_num={workspace_num}")
    print(f"checkout_target={resolved.checkout_target}")
    print(f"primary_workspace_dir={resolved.primary_workspace_dir}")
    print(f"should_release={'true' if release else 'false'}")
    print(f"_chdir={workspace_dir}")
    print(f"meta_workspace={workspace_num}")
