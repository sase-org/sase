"""Release step for the #git xprompt workflow."""

from sase.workspace_provider.vcs_release import VcsReleaseResult, release_vcs_workspace

_CALLER_TAG = "git-release"


def main(
    *,
    project_file: str,
    workspace_num: int,
    workspace_dir: str,
    workflow_name: str,
    cl_name: str | None,
) -> None:
    """Identity-checked, handoff-aware release of the #git workspace claim."""
    result: VcsReleaseResult = release_vcs_workspace(
        project_file=project_file,
        workspace_num=workspace_num,
        workspace_dir=workspace_dir,
        workflow_name=workflow_name,
        cl_name=cl_name,
        caller_tag=_CALLER_TAG,
    )
    print(f"released={'true' if result.released else 'false'}")
    if result.skip_reason:
        print(f"skip_reason={result.skip_reason}")
