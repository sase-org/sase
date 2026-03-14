"""Discovery and dispatch for workspace provider plugins."""

from __future__ import annotations

import functools
import importlib.metadata
import re
from typing import TYPE_CHECKING

import pluggy

if TYPE_CHECKING:
    from rich.console import Console

from ._hookspec import ResolvedRef, WorkflowMetadata, WorkspaceHookSpec
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


@functools.cache
def get_all_workflow_metadata() -> tuple[WorkflowMetadata, ...]:
    """Return metadata from all workspace plugins, cached."""
    return tuple(_get_manager().get_workflow_metadata())


def get_workflow_names() -> set[str]:
    """Return the set of all registered workflow type names."""
    return {m.workflow_type for m in get_all_workflow_metadata()}


def get_ref_patterns() -> dict[str, re.Pattern[str]]:
    """Return a mapping of workflow_type → compiled ref pattern."""
    return {
        m.workflow_type: re.compile(m.ref_pattern) for m in get_all_workflow_metadata()
    }


def get_display_name(workflow_type: str) -> str | None:
    """Return the display name for *workflow_type*, or ``None``."""
    for m in get_all_workflow_metadata():
        if m.workflow_type == workflow_type:
            return m.display_name
    return None


def get_display_name_by_vcs_family(vcs_family: str) -> str | None:
    """Return a display name for a ``detect_vcs_family()`` result.

    Finds the first registered workflow whose ``vcs_family`` field matches
    *vcs_family* and returns its ``display_name``.
    """
    for m in get_all_workflow_metadata():
        if m.vcs_family == vcs_family:
            return m.display_name
    return None


def get_display_name_by_vcs(vcs_name: str) -> str | None:
    """Return a display name for a :func:`~sase.vcs_provider.detect_vcs` result.

    Finds the registered workflow whose ``vcs_provider_name`` matches
    *vcs_name* and returns its ``display_name``.  Falls back to
    :func:`get_display_name_by_vcs_family` when no exact match is found.
    """
    for m in get_all_workflow_metadata():
        if m.vcs_provider_name == vcs_name:
            return m.display_name
    # Fall back to family-based lookup for plugins that haven't set
    # vcs_provider_name yet.
    vcs_family = "git" if vcs_name in ("github", "bare_git") else vcs_name
    return get_display_name_by_vcs_family(vcs_family)


def get_pre_allocated_env_prefix(workflow_type: str) -> str | None:
    """Return the env-var prefix for *workflow_type*, or ``None``."""
    for m in get_all_workflow_metadata():
        if m.workflow_type == workflow_type:
            return m.pre_allocated_env_prefix
    return None


def get_vcs_tag_pattern() -> re.Pattern[str]:
    """Build a regex matching any VCS workflow tag at the start of a prompt."""
    names = "|".join(re.escape(n) for n in sorted(get_workflow_names()))
    return re.compile(rf"^#(?:{names})(?:!!|\?\?)?(?:\([^)]*\)|\+|[_:][^\s]*|)\s")


def detect_workflow_type(project_file: str) -> str:
    """Detect the workflow type for *project_file* via plugins.

    Returns ``"gh"``, ``"git"``, ``"hg"``, etc.

    Raises:
        ValueError: If no plugin claims the project.
    """
    result = _get_manager().detect_workflow_type(project_file)
    if result is not None:
        return result
    raise ValueError(
        f"No workspace plugin detected a workflow type for '{project_file}'. "
        f"Install the appropriate workspace plugin."
    )


def get_change_label(project_file: str) -> str:
    """Return the change label (``"PR"`` or ``"CL"``) for *project_file*.

    Falls back to legacy detection when no plugin claims the project.
    """
    result = _get_manager().get_change_label(project_file)
    if result is not None:
        return result
    raise ValueError(
        f"No workspace plugin provided a change label for '{project_file}'. "
        f"Install the appropriate workspace plugin."
    )


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

    raise ValueError(f"No workspace plugin found for workflow type '{workflow_type}'")


def extract_change_identifier(cl_url: str) -> tuple[str, str] | None:
    """Extract the change identifier and VCS type from a CL/PR URL via plugins."""
    return _get_manager().extract_change_identifier(cl_url)


def generate_submitted_check_script(identifier: str, vcs_type: str) -> str | None:
    """Generate a bash script body to check if a change is submitted via plugins."""
    return _get_manager().generate_submitted_check_script(identifier, vcs_type)


def supports_reviewer_comments(cl_url: str) -> bool | None:
    """Check if the given CL URL supports reviewer comments via plugins."""
    return _get_manager().supports_reviewer_comments(cl_url)


def generate_reviewer_comments_script(changespec_name: str) -> str | None:
    """Generate a bash script body to fetch reviewer comments via plugins."""
    return _get_manager().generate_reviewer_comments_script(changespec_name)


def get_workspace_directory(
    workflow_type: str,
    workspace_num: int,
    project_name: str,
    primary_workspace_dir: str,
) -> str:
    """Get the workspace directory for a given workflow type and workspace number.

    Delegates to workspace provider plugins via the
    ``ws_get_workspace_directory`` hook.

    Raises:
        RuntimeError: If no plugin handles the workflow type.
    """
    result = _get_manager().get_workspace_directory(
        workflow_type, workspace_num, project_name, primary_workspace_dir
    )
    if result is not None:
        return result
    raise RuntimeError(
        f"No workspace plugin provided a workspace directory for "
        f"workflow type '{workflow_type}'"
    )


def prepare_mail(
    changespec_name: str,
    changespec_parent: str | None,
    project_basename: str,
    project_file: str,
    target_dir: str,
    console: Console | None = None,
) -> object | None:
    """Prepare mail/PR via workspace provider plugins.

    Delegates to the ``ws_prepare_mail`` hook.  Returns a
    ``MailPrepResult``-compatible object or ``None`` if no plugin
    handled the project.
    """
    return _get_manager().prepare_mail(
        changespec_name=changespec_name,
        changespec_parent=changespec_parent,
        project_basename=project_basename,
        project_file=project_file,
        target_dir=target_dir,
        console=console,
    )


def format_commit_description(
    file_path: str,
    project: str,
    workflow_type: str,
    bug: str | None = None,
    fixed_bug: str | None = None,
) -> None:
    """Format a commit description file via workspace provider plugins.

    Delegates to the ``ws_format_commit_description`` hook.  Falls back
    to writing a simple ``[project] content`` prefix when no plugin
    handles the workflow type.
    """
    result = _get_manager().format_commit_description(
        file_path, project, workflow_type, bug=bug, fixed_bug=fixed_bug
    )
    if result is not None:
        return

    # Fallback: simple project prefix (same as git behavior)
    with open(file_path, encoding="utf-8") as f:
        content = f.read()
    with open(file_path, "w", encoding="utf-8") as f:
        f.write(f"[{project}] {content}\n")


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

    return (False, "No workspace plugin handled submission for this project.")
