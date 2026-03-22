"""Workspace number allocation and directory resolution."""

from sase.running_field._operations import get_claimed_workspaces


def get_first_available_workspace(project_file: str, max_workspaces: int = 99) -> int:
    """Find the first available (unclaimed) workspace number.

    Args:
        project_file: Path to the ProjectSpec file
        max_workspaces: Maximum workspace number to check (1-99)

    Returns:
        First available workspace number (1 = main, 2+ = shares)
    """
    claims = get_claimed_workspaces(project_file)
    claimed_nums = {claim.workspace_num for claim in claims}

    # Find first unclaimed workspace number
    for n in range(1, max_workspaces + 1):
        if n not in claimed_nums:
            return n

    # All workspaces claimed - return 1 as fallback
    return 1


def get_first_available_axe_workspace(
    project_file: str, min_workspace: int = 100, max_workspace: int = 199
) -> int:
    """Find the first available (unclaimed) workspace number for axe hooks.

    Axe hooks use workspace numbers >= 100 to avoid conflicts with regular
    workflows that use workspaces 1-99.

    Args:
        project_file: Path to the ProjectSpec file
        min_workspace: Minimum workspace number to consider (default: 100)
        max_workspace: Maximum workspace number to consider (default: 199)

    Returns:
        First available workspace number in the axe range (100-199)
    """
    claims = get_claimed_workspaces(project_file)
    claimed_nums = {claim.workspace_num for claim in claims}

    # Find first unclaimed workspace number in axe range
    for n in range(min_workspace, max_workspace + 1):
        if n not in claimed_nums:
            return n

    # All axe workspaces claimed - return min_workspace as fallback
    return min_workspace


def get_workspace_directory_for_num(
    workspace_num: int, project_basename: str, *, clean: bool = True
) -> tuple[str, str | None]:
    """Get the workspace directory path for a given workspace number.

    Calls sase_hg_get_workspace to get the directory path, which will create
    workspace shares if they don't exist.

    For non-main workspaces (workspace_num > 1), automatically cleans the
    workspace to revert any uncommitted changes before returning.  This
    prevents ``checkout`` / ``hg update`` failures caused by leftover dirty
    state from a previous run.

    Args:
        workspace_num: Workspace number (1 = main, 2+ = shares)
        project_basename: Project name
        clean: If True (default), clean non-main workspaces before returning.

    Returns:
        Tuple of (workspace_directory, workspace_suffix)
        - workspace_directory: Full path to workspace directory
        - workspace_suffix: Suffix like "fig_3" or None for main workspace

    Raises:
        RuntimeError: If sase_hg_get_workspace command fails
    """
    workspace_dir = get_workspace_directory(project_basename, workspace_num)

    if workspace_num == 1:
        return (workspace_dir, None)

    # Clean non-main workspaces to avoid checkout conflicts from leftover
    # dirty state.
    if clean:
        from sase.workflows.commit_utils import clean_workspace

        clean_workspace(workspace_dir)

    workspace_suffix = f"{project_basename}_{workspace_num}"
    return (workspace_dir, workspace_suffix)


def get_workspace_directory(project: str, workspace_num: int = 1) -> str:
    """Get the workspace directory path for a project.

    Delegates to workspace provider plugins via the
    ``ws_get_workspace_directory`` hook.

    Args:
        project: Project name (e.g., "foobar")
        workspace_num: Workspace number (1 = main, 2+ = shares)

    Returns:
        Full path to workspace directory

    Raises:
        RuntimeError: If workspace resolution fails
    """
    from sase.workspace_provider import (
        detect_workflow_type,
        get_workspace_directory as ws_get_workspace_directory,
    )
    from sase.workspace_provider.utils import parse_workspace_dir
    from sase.workflows.utils import get_project_file_path

    project_file = get_project_file_path(project)
    try:
        workflow_type = detect_workflow_type(project_file)
    except ValueError as e:
        raise RuntimeError(str(e)) from e
    workspace_dir = parse_workspace_dir(project_file) or ""
    return ws_get_workspace_directory(
        workflow_type, workspace_num, project, workspace_dir
    )
