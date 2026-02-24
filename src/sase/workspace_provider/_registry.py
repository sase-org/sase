"""Discovery and dispatch for workspace provider plugins."""

from __future__ import annotations

import importlib.metadata
from typing import TYPE_CHECKING

import pluggy

if TYPE_CHECKING:
    from rich.console import Console

from ._hookspec import ResolvedRef, WorkspaceHookSpec
from ._plugin_manager import WorkspacePluginManager

_manager: WorkspacePluginManager | None = None


def _get_manager() -> WorkspacePluginManager:
    """Return the singleton :class:`WorkspacePluginManager`.

    Lazily creates the manager on first call, loading ALL
    ``sase_workspace`` entry-point plugins.
    """
    global _manager  # noqa: PLW0603
    if _manager is None:
        pm = pluggy.PluginManager("sase_workspace")
        pm.add_hookspecs(WorkspaceHookSpec)
        for ep in importlib.metadata.entry_points(group="sase_workspace"):
            plugin_class = ep.load()
            pm.register(plugin_class())
        _manager = WorkspacePluginManager(pm)
    return _manager


def detect_workflow_type(project_file: str) -> str:
    """Detect the workflow type for *project_file* via plugins.

    Returns ``"gh"``, ``"git"``, ``"hg"``, etc.  Falls back to legacy
    detection when no plugin claims the project.
    """
    result = _get_manager().detect_workflow_type(project_file)
    if result is not None:
        return result
    # Fallback to legacy detection (covers "gh" and "hg" until those plugins exist)
    from sase.gh_workspace import detect_workflow_type_for_project

    return detect_workflow_type_for_project(project_file)


def get_change_label(project_file: str) -> str:
    """Return the change label (``"PR"`` or ``"CL"``) for *project_file*.

    Falls back to legacy detection when no plugin claims the project.
    """
    result = _get_manager().get_change_label(project_file)
    if result is not None:
        return result
    # Fallback to legacy
    from sase.workspace_utils import get_cl_field_label

    return get_cl_field_label(project_file)


def resolve_ref(ref: str, workflow_type: str) -> ResolvedRef:
    """Resolve a workspace reference via plugins.

    Falls back to legacy resolution functions when no plugin handles
    the *workflow_type*.

    Raises:
        ValueError: If the reference cannot be resolved.
    """
    result = _get_manager().resolve_ref(ref, workflow_type)
    if result is not None:
        return result

    # Fallback to legacy resolution
    if workflow_type == "gh":
        from sase.gh_workspace import resolve_gh_ref

        r = resolve_gh_ref(ref)
        return ResolvedRef(
            project_file=r.project_file,
            project_name=r.project_name,
            primary_workspace_dir=r.primary_workspace_dir,
            checkout_target=r.checkout_target,
        )
    if workflow_type == "git":
        from sase.git_workspace import resolve_git_ref

        git_ref = resolve_git_ref(ref)
        return ResolvedRef(
            project_file=git_ref.project_file,
            project_name=git_ref.project_name,
            primary_workspace_dir=git_ref.primary_workspace_dir,
            checkout_target=git_ref.checkout_target,
            extra={"bare_repo_dir": git_ref.bare_repo_dir},
        )
    raise ValueError(f"No workspace plugin found for workflow type '{workflow_type}'")


def submit_changespec(
    changespec_file: str,
    changespec_name: str,
    project_basename: str,
    console: Console | None = None,
) -> tuple[bool, str | None]:
    """Submit a changespec via plugins.

    Falls back to legacy submission when no plugin handles the project.
    """
    result = _get_manager().submit(
        changespec_file, changespec_name, project_basename, console
    )
    if result is not None:
        return result

    # Fallback to legacy submission
    from sase.ace.changespec import find_all_changespecs
    from sase.git_submit import submit_git_changespec

    for cs in find_all_changespecs():
        if cs.name == changespec_name:
            return submit_git_changespec(cs, console)
    return (False, f"ChangeSpec '{changespec_name}' not found")
