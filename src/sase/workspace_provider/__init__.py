"""Workspace provider plugin system.

Usage::

    from sase.workspace_provider import detect_workflow_type, get_change_label

    wf_type = detect_workflow_type(project_file)
    label = get_change_label(project_file)
"""

from ._hookspec import ResolvedRef, WorkspaceHookSpec, hookimpl, hookspec
from ._plugin_manager import WorkspacePluginManager
from ._registry import (
    detect_workflow_type,
    get_change_label,
    resolve_ref,
    submit_changespec,
)

__all__ = [
    "ResolvedRef",
    "WorkspaceHookSpec",
    "WorkspacePluginManager",
    "detect_workflow_type",
    "get_change_label",
    "hookimpl",
    "hookspec",
    "resolve_ref",
    "submit_changespec",
]
