"""Functions for formatting CL descriptions."""


def format_cl_description(
    file_path: str,
    project: str,
    bug: str | None = None,
    fixed_bug: str | None = None,
    vcs_type: str = "hg",
) -> None:
    """Format the CL description file with project tag and metadata.

    .. deprecated::
        Use :func:`sase.workspace_provider.format_commit_description`
        instead, which delegates to workspace provider plugins.  This
        function is retained for backward compatibility and now delegates
        to the plugin hook internally.

    Args:
        file_path: Path to the file containing the CL description.
        project: Project name to prepend to the description.
        bug: Bug number for BUG= tag. Mutually exclusive with fixed_bug.
        fixed_bug: Bug number for FIXED= tag. Mutually exclusive with bug.
        vcs_type: VCS family (``"hg"`` or ``"git"``). Mapped to
            workflow type for plugin dispatch.
    """
    from sase.workspace_provider import format_commit_description

    # Map VCS family to workflow type for plugin dispatch.
    # "git" maps to "git" (bare-git); "hg" maps to "hg".
    workflow_type = vcs_type
    format_commit_description(
        file_path, project, workflow_type, bug=bug, fixed_bug=fixed_bug
    )
