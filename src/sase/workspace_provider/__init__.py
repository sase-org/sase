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
    extract_change_identifier,
    format_commit_description,
    generate_reviewer_comments_script,
    generate_submitted_check_script,
    get_all_workflow_metadata,
    get_change_label,
    get_display_name,
    get_display_name_by_vcs,
    get_display_name_by_vcs_family,
    get_pre_allocated_env_prefix,
    get_ref_patterns,
    get_vcs_tag_pattern,
    get_workflow_names,
    get_workspace_directory,
    prepare_mail,
    resolve_ref,
    submit_changespec,
    supports_reviewer_comments,
)

__all__ = [
    "ResolvedRef",
    "WorkflowMetadata",
    "WorkspaceHookSpec",
    "WorkspacePluginManager",
    "detect_workflow_type",
    "extract_change_identifier",
    "format_commit_description",
    "generate_reviewer_comments_script",
    "generate_submitted_check_script",
    "get_all_workflow_metadata",
    "get_change_label",
    "get_display_name",
    "get_display_name_by_vcs",
    "get_display_name_by_vcs_family",
    "get_pre_allocated_env_prefix",
    "get_ref_patterns",
    "get_vcs_tag_pattern",
    "get_workflow_names",
    "get_workspace_directory",
    "hookimpl",
    "hookspec",
    "prepare_mail",
    "resolve_ref",
    "submit_changespec",
    "supports_reviewer_comments",
]
