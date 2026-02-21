"""Setup step for the #hg xprompt workflow."""

import os

from sase.ace.changespec import find_all_changespecs
from sase.running_field import (
    claim_workspace,
    get_first_available_axe_workspace,
    get_workspace_directory_for_num,
)


def main(*, cl_name: str, n: int | None, release: bool) -> None:
    """Resolve changespec/project, claim a workspace, and print config.

    Prints key=value output for the workflow executor.
    """
    cs_match = None
    for cs in find_all_changespecs():
        if cs.name == cl_name:
            cs_match = cs
            break

    if cs_match:
        project_name = cs_match.project_basename
        project_file = cs_match.file_path
    else:
        # Fallback: project shorthand
        candidate = os.path.expanduser(f"~/.sase/projects/{cl_name}/{cl_name}.gp")
        if os.path.isfile(candidate):
            project_name = cl_name
            project_file = candidate
        else:
            raise RuntimeError(f"'{cl_name}' not found as a ChangeSpec name or project")

    # Check if workspace was pre-allocated by the TUI
    if os.environ.get("SASE_HG_PRE_ALLOCATED") == "1":
        workspace_num = int(os.environ["SASE_HG_WORKSPACE_NUM"])
        workspace_dir = os.environ["SASE_HG_WORKSPACE_DIR"]
    elif n is not None:
        workspace_num = n
        workspace_dir, _ = get_workspace_directory_for_num(workspace_num, project_name)
    else:
        workspace_num = get_first_available_axe_workspace(project_file)
        workspace_dir, _ = get_workspace_directory_for_num(workspace_num, project_name)

    pid = os.getpid()
    workflow_name = f"hg-{cl_name}"
    claim_workspace(
        project_file,
        workspace_num,
        workflow_name,
        pid,
        cl_name,
        pinned=not release,
    )

    print(f"project_name={project_name}")
    print(f"project_file={project_file}")
    print(f"workspace_dir={workspace_dir}")
    print(f"workspace_num={workspace_num}")
    print(f"_chdir={workspace_dir}")
    print(f"meta_workspace={workspace_num}")
    checkout_target = cl_name if cs_match else "p4head"

    if cs_match:
        print(f"meta_changespec={cl_name}")
    else:
        print(f"meta_project={cl_name}")
    print(f"checkout_target={checkout_target}")
    print(f"should_release={'true' if release else 'false'}")
