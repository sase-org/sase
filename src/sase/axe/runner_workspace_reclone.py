"""Re-creation retry around axe workspace preparation."""

from collections.abc import Callable

from sase.axe.runner_workspace_errors import WorkspacePreparationError


def prepare_workspace_with_reclone(
    prepare: Callable[..., None],
    *,
    workspace_dir: str,
    workspace_num: int,
    cl_name: str,
    update_target: str,
    project_basename: str = "",
    backup_suffix: str = "ace",
    project_file: str | None = None,
    after_recreate: Callable[[], None] | None = None,
) -> None:
    """Prepare the checkout, re-creating it once when in-place healing fails.

    Runs *prepare* (the caller's ``prepare_workspace`` entry point, kept as a
    parameter so each caller's patch surface stays intact) with self-heal for
    numbered workspaces. When it raises a re-creation-eligible
    :class:`WorkspacePreparationError`, the managed checkout is rescued and
    re-materialized from the primary checkout, *after_recreate* re-enters the
    new checkout (chdir, derived environment, occupancy re-check), and
    *prepare* runs once more. A second failure propagates to the caller.

    Fetch and network failures are never eligible and propagate immediately,
    as does every failure for the primary checkout (``workspace_num <= 1``).
    """
    from sase.workspace_provider.utils import recreate_managed_workspace

    try:
        prepare(
            workspace_dir,
            cl_name,
            update_target,
            backup_suffix=backup_suffix,
            project_basename=project_basename,
            self_heal=workspace_num > 1,
            workspace_num=workspace_num,
        )
        return
    except WorkspacePreparationError as exc:
        if not exc.reclone_eligible or workspace_num <= 1:
            raise
        print(
            f"Workspace #{workspace_num} could not be repaired in place "
            f"({exc.reason}); re-creating it from the primary checkout..."
        )
    recreate_managed_workspace(workspace_dir, workspace_num, project_file=project_file)
    if after_recreate is not None:
        after_recreate()
    prepare(
        workspace_dir,
        cl_name,
        update_target,
        backup_suffix=backup_suffix,
        project_basename=project_basename,
        self_heal=workspace_num > 1,
        workspace_num=workspace_num,
    )


__all__ = ["prepare_workspace_with_reclone"]
