"""Workspace provider plugin system.

Usage::

    from sase.workspace_provider import detect_workflow_type, get_change_label

    wf_type = detect_workflow_type(project_file)
    label = get_change_label(project_file)
"""

from ._hookspec import (
    ResolvedRef,
    WorkflowMetadata,
    WorkspaceHookSpec,
    hookimpl,
    hookspec,
)
from ._plugin_manager import WorkspacePluginManager
from ._registry import (
    detect_workflow_type,
    get_all_workflow_metadata,
    get_change_label,
    get_display_name,
    get_display_name_by_vcs_family,
    get_pre_allocated_env_prefix,
    get_ref_patterns,
    get_vcs_tag_pattern,
    get_workflow_names,
    resolve_ref,
    submit_changespec,
)

__all__ = [
    "ResolvedRef",
    "WorkflowMetadata",
    "WorkspaceHookSpec",
    "WorkspacePluginManager",
    "detect_workflow_type",
    "get_all_workflow_metadata",
    "get_change_label",
    "get_display_name",
    "get_display_name_by_vcs_family",
    "get_pre_allocated_env_prefix",
    "get_ref_patterns",
    "get_vcs_tag_pattern",
    "get_workflow_names",
    "hookimpl",
    "hookspec",
    "resolve_ref",
    "submit_changespec",
]
