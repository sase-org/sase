"""Create changespec step for the #pr xprompt workflow."""

import os

from sase.gh_workspace import get_default_branch
from sase.vcs_provider import get_vcs_provider
from sase.workflow_utils import get_project_file_path
from sase.workspace_changespec import create_changespec_for_workflow


def main(*, name: str, prompt: str, response: str) -> None:
    """Derive project info from cwd and create a changespec.

    Prints key=value output for the workflow executor.
    """
    provider = get_vcs_provider(os.getcwd())
    ok, project_name = provider.get_workspace_name(os.getcwd())
    if not ok or not project_name:
        print("success=false")
        print("error=Could not determine project name from workspace")
        print("cl_name=")
        print("project_file=")
        print("default_branch=")
        return

    project_file = get_project_file_path(project_name)

    # Determine default branch
    default_branch_ref = get_default_branch(os.getcwd())
    default_branch = default_branch_ref.rsplit("/", 1)[-1]

    # Build CL name: {project}_{name_with_underscores}
    cl_name = f"{project_name}_{name.replace('-', '_')}"

    result = create_changespec_for_workflow(
        project_name=project_name,
        project_file=project_file,
        checkout_target=f"origin/{default_branch}",
        branch_name=name,
        prompt=prompt,
        response=response,
        workflow_name="pr",
        cl_name=cl_name,
    )

    if result:
        print("success=true")
        print(f"cl_name={result}")
        print(f"project_file={project_file}")
        print(f"default_branch={default_branch}")
        print(f"meta_changespec={result}")
        print("error=")
    else:
        print("success=false")
        print("cl_name=")
        print(f"project_file={project_file}")
        print(f"default_branch={default_branch}")
        print("error=No new commits found")
