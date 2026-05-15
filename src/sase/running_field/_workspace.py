"""Workspace number allocation and directory resolution."""

from sase.running_field._operations import get_claimed_workspaces

# Unified claim pool. ``#0`` is the primary checkout / deferred placeholder and
# numbers ``#1``-``#9`` are reserved. Claim-backed workspaces (workflow shares
# and axe-launched agents alike) allocate from a single unified pool starting
# at ``#10``.
RESERVED_MAX_WORKSPACE = 9
UNIFIED_MIN_WORKSPACE = 10
UNIFIED_MAX_WORKSPACE = 999


def get_first_available_workspace(
    project_file: str,
    min_workspace: int = UNIFIED_MIN_WORKSPACE,
    max_workspace: int = UNIFIED_MAX_WORKSPACE,
) -> int:
    """Find the first available (unclaimed) workspace number.

    Allocates from the unified claim pool (default ``10-999``).  Workspace
    ``#0`` is the primary checkout / deferred placeholder and ``#1``-``#9``
    are reserved; callers that need a legacy range can pass explicit
    ``min_workspace`` / ``max_workspace`` bounds.

    Args:
        project_file: Path to the ProjectSpec file
        min_workspace: Minimum workspace number to consider (default: 10)
        max_workspace: Maximum workspace number to consider (default: 999)

    Returns:
        First available workspace number in the configured range.

    Raises:
        RuntimeError: If every workspace in the range is claimed.
    """
    claims = get_claimed_workspaces(project_file)
    claimed_nums = {claim.workspace_num for claim in claims}

    for n in range(min_workspace, max_workspace + 1):
        if n not in claimed_nums:
            return n

    raise RuntimeError(
        f"All workspaces ({min_workspace}-{max_workspace}) are claimed "
        f"in {project_file}"
    )


def get_first_available_axe_workspace(
    project_file: str,
    min_workspace: int = UNIFIED_MIN_WORKSPACE,
    max_workspace: int = UNIFIED_MAX_WORKSPACE,
) -> int:
    """Find the first available (unclaimed) workspace number for axe hooks.

    Axe hooks share the unified claim pool (default ``10-999``) with other
    claim-backed workspaces.  Workspace ``#0`` remains the deferred
    placeholder and ``#1``-``#9`` are reserved.  Tests and advanced callers
    may pass explicit ``min_workspace`` / ``max_workspace`` to exercise a
    legacy range.

    Args:
        project_file: Path to the ProjectSpec file
        min_workspace: Minimum workspace number to consider (default: 10)
        max_workspace: Maximum workspace number to consider (default: 999)

    Returns:
        First available workspace number in the configured range.

    Raises:
        RuntimeError: If every workspace in the range is claimed.
    """
    claims = get_claimed_workspaces(project_file)
    claimed_nums = {claim.workspace_num for claim in claims}

    for n in range(min_workspace, max_workspace + 1):
        if n not in claimed_nums:
            return n

    raise RuntimeError(
        f"All axe workspaces ({min_workspace}-{max_workspace}) are claimed "
        f"in {project_file}"
    )


def _normalize_legacy_primary(workspace_num: int) -> int:
    """Map the legacy ``#1`` primary identity to ``#0`` for store lookups.

    Phase 4 reserved ``1-9`` so the only remaining caller passing ``1`` is
    legacy code that still means "primary checkout".  ``WorkspaceStore``
    treats ``#0`` as primary in every root policy; without this translation
    a ``workspace.root: xdg-state`` config would try to materialize a
    managed ``proj_1/`` clone for a primary lookup.
    """
    return 0 if workspace_num == 1 else workspace_num


def get_workspace_directory_for_num(
    workspace_num: int, project_basename: str, *, clean: bool = True
) -> tuple[str, str | None]:
    """Get the workspace directory path for a given workspace number.

    For the primary checkout (``workspace_num`` ``0`` or legacy ``1``)
    the returned suffix is ``None`` and no cleanup is performed.  For
    managed checkouts (``workspace_num >= 2``) the resolved directory is
    cleaned by default so subsequent ``checkout`` / ``update`` calls do
    not trip over leftover dirty state.

    Args:
        workspace_num: Workspace number (``0``/``1`` = primary, ``2+`` = managed)
        project_basename: Project name
        clean: If True (default), clean managed workspaces before returning.

    Returns:
        Tuple of (workspace_directory, workspace_suffix)
        - workspace_directory: Full path to workspace directory
        - workspace_suffix: Suffix like "fig_3" or None for the primary
    """
    workspace_dir = get_workspace_directory(project_basename, workspace_num)

    if workspace_num <= 1:
        return (workspace_dir, None)

    if clean:
        from sase.workflows.commit_utils import clean_workspace

        clean_workspace(workspace_dir)

    workspace_suffix = f"{project_basename}_{workspace_num}"
    return (workspace_dir, workspace_suffix)


def get_workspace_directory(project: str, workspace_num: int = 1) -> str:
    """Get the workspace directory path for a project.

    Compatibility wrapper that maps legacy ``workspace_num == 1`` to the
    new primary identity ``#0`` and delegates to workspace provider
    plugins via the ``ws_get_workspace_directory`` hook.

    Args:
        project: Project name (e.g., "foobar")
        workspace_num: Workspace number (``0``/``1`` = primary, ``2+`` = managed)

    Returns:
        Full path to workspace directory

    Raises:
        RuntimeError: If workspace resolution fails
    """
    import os

    from sase.workspace_provider import (
        detect_workflow_type,
        get_workspace_directory as ws_get_workspace_directory,
    )
    from sase.workspace_provider.utils import (
        ensure_workspace_checkout,
        parse_workspace_dir,
    )
    from sase.workflows.utils import get_project_file_path

    workspace_num = _normalize_legacy_primary(workspace_num)

    project_file = get_project_file_path(project)
    workspace_dir = parse_workspace_dir(project_file) or ""
    try:
        workflow_type = detect_workflow_type(project_file)
    except ValueError as e:
        # Generic fallback: if no workspace plugin claims the project but the
        # project file declares a usable WORKSPACE_DIR, route the workspace
        # request through that directory directly. This keeps configured agent
        # chops working when provider entry points are temporarily unavailable
        # (e.g. fresh source checkouts without the GitHub plugin installed).
        if workspace_dir and os.path.isdir(workspace_dir):
            if workspace_num == 0:
                return workspace_dir
            if os.path.isdir(os.path.join(workspace_dir, ".git")):
                return ensure_workspace_checkout(workspace_dir, workspace_num)
        raise RuntimeError(str(e)) from e
    return ws_get_workspace_directory(
        workflow_type, workspace_num, project, workspace_dir
    )
