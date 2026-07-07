"""Workspace provider plugin system.

Usage::

    from sase.workspace_provider import detect_workflow_type, get_change_label

    wf_type = detect_workflow_type(project_file)
    label = get_change_label(project_file)
"""

from ._hookspec import (
    ResolvedRef,
    SUBMITTED_CHECK_EXIT_CODE_CLOSED,
    VcsRepoCandidates,
    VcsRepoEntry,
    WorkflowMetadata,
    WorkspaceHookSpec,
    hookimpl,
    hookspec,
)
from ._plugin_manager import WorkspacePluginManager
from .marker import (
    CheckoutMarker,
    find_marker_from_cwd,
    read_marker,
    write_marker,
)
from .registry import (
    WorkspaceEntry,
    WorkspaceRegistry,
    load_or_init_registry,
    record_workspace,
    remove_workspace,
    save_registry,
)
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
    get_embedded_vcs_tag_pattern,
    get_ref_patterns,
    get_vcs_tag_pattern,
    get_workflow_names,
    get_workspace_directory,
    get_workspace_name,
    list_repo_candidates,
    peek_ref,
    prepare_mail,
    resolve_ref,
    submit_changespec,
    supports_reviewer_comments,
)

__all__ = [
    "CheckoutMarker",
    "ResolvedRef",
    "SUBMITTED_CHECK_EXIT_CODE_CLOSED",
    "VcsRepoCandidates",
    "VcsRepoEntry",
    "WorkflowMetadata",
    "WorkspaceEntry",
    "WorkspaceHookSpec",
    "WorkspacePluginManager",
    "WorkspaceRegistry",
    "detect_workflow_type",
    "extract_change_identifier",
    "find_marker_from_cwd",
    "format_commit_description",
    "generate_reviewer_comments_script",
    "generate_submitted_check_script",
    "get_all_workflow_metadata",
    "get_change_label",
    "get_display_name",
    "get_display_name_by_vcs",
    "get_display_name_by_vcs_family",
    "get_embedded_vcs_tag_pattern",
    "get_pre_allocated_env_prefix",
    "get_ref_patterns",
    "get_vcs_tag_pattern",
    "get_workflow_names",
    "get_workspace_directory",
    "get_workspace_name",
    "hookimpl",
    "hookspec",
    "list_repo_candidates",
    "load_or_init_registry",
    "peek_ref",
    "prepare_mail",
    "read_marker",
    "record_workspace",
    "remove_workspace",
    "resolve_ref",
    "save_registry",
    "submit_changespec",
    "supports_reviewer_comments",
    "write_marker",
]
