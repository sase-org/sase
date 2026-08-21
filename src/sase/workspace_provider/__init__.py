"""Workspace provider plugin system.

Usage::

    from sase.workspace_provider import detect_workflow_type, get_change_label

    wf_type = detect_workflow_type(project_file)
    label = get_change_label(project_file)
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from sase._lazy_exports import lazy_dir, lazy_getattr

_HOOKSPEC = "sase.workspace_provider._hookspec"
_REGISTRY_IMPL = "sase.workspace_provider._registry"
_LAZY_EXPORTS = {
    "ExternalRepoCloneResult": (_HOOKSPEC, "ExternalRepoCloneResult"),
    "ResolvedRef": (_HOOKSPEC, "ResolvedRef"),
    "SddSidecarPreflight": (_HOOKSPEC, "SddSidecarPreflight"),
    "SddSidecarPreflightStatus": (
        _HOOKSPEC,
        "SddSidecarPreflightStatus",
    ),
    "SUBMITTED_CHECK_EXIT_CODE_CLOSED": (
        _HOOKSPEC,
        "SUBMITTED_CHECK_EXIT_CODE_CLOSED",
    ),
    "VcsNamespaceEntry": (_HOOKSPEC, "VcsNamespaceEntry"),
    "VcsRefNamespaces": (_HOOKSPEC, "VcsRefNamespaces"),
    "VcsRepoCandidates": (_HOOKSPEC, "VcsRepoCandidates"),
    "VcsRepoEntry": (_HOOKSPEC, "VcsRepoEntry"),
    "WorkflowMetadata": (_HOOKSPEC, "WorkflowMetadata"),
    "WorkspaceHookSpec": (_HOOKSPEC, "WorkspaceHookSpec"),
    "hookimpl": (_HOOKSPEC, "hookimpl"),
    "hookspec": (_HOOKSPEC, "hookspec"),
    "WorkspacePluginManager": (
        "sase.workspace_provider._plugin_manager",
        "WorkspacePluginManager",
    ),
    "resolve_consistent_workspace_pair": (
        "sase.workspace_provider.lookup",
        "resolve_consistent_workspace_pair",
    ),
    "resolve_workspace_num_for_dir": (
        "sase.workspace_provider.lookup",
        "resolve_workspace_num_for_dir",
    ),
    "CheckoutMarker": ("sase.workspace_provider.marker", "CheckoutMarker"),
    "find_marker_from_cwd": (
        "sase.workspace_provider.marker",
        "find_marker_from_cwd",
    ),
    "read_marker": ("sase.workspace_provider.marker", "read_marker"),
    "write_marker": ("sase.workspace_provider.marker", "write_marker"),
    "AccessKind": ("sase.workspace_provider.ownership", "AccessKind"),
    "MutationOrigin": ("sase.workspace_provider.ownership", "MutationOrigin"),
    "OperationContext": (
        "sase.workspace_provider.ownership",
        "OperationContext",
    ),
    "WorkspaceOwnershipError": (
        "sase.workspace_provider.ownership",
        "WorkspaceOwnershipError",
    ),
    "authorize_store_mutation": (
        "sase.workspace_provider.ownership",
        "authorize_store_mutation",
    ),
    "leased_operational_context": (
        "sase.workspace_provider.ownership",
        "leased_operational_context",
    ),
    "normalize_workspace_num": (
        "sase.workspace_provider.ownership",
        "normalize_workspace_num",
    ),
    "primary_sidecar_sync_context": (
        "sase.workspace_provider.ownership",
        "primary_sidecar_sync_context",
    ),
    "read_only_canonical_context": (
        "sase.workspace_provider.ownership",
        "read_only_canonical_context",
    ),
    "user_directed_context": (
        "sase.workspace_provider.ownership",
        "user_directed_context",
    ),
    "writable_beads_dir": (
        "sase.workspace_provider.ownership",
        "writable_beads_dir",
    ),
    "writable_checkout_dir": (
        "sase.workspace_provider.ownership",
        "writable_checkout_dir",
    ),
    "writable_kind_root": (
        "sase.workspace_provider.ownership",
        "writable_kind_root",
    ),
    "writable_plans_dir": (
        "sase.workspace_provider.ownership",
        "writable_plans_dir",
    ),
    "writable_sidecar_root": (
        "sase.workspace_provider.ownership",
        "writable_sidecar_root",
    ),
    "WorkspaceEntry": ("sase.workspace_provider.registry", "WorkspaceEntry"),
    "WorkspaceRegistry": (
        "sase.workspace_provider.registry",
        "WorkspaceRegistry",
    ),
    "load_or_init_registry": (
        "sase.workspace_provider.registry",
        "load_or_init_registry",
    ),
    "record_workspace": (
        "sase.workspace_provider.registry",
        "record_workspace",
    ),
    "remove_workspace": (
        "sase.workspace_provider.registry",
        "remove_workspace",
    ),
    "save_registry": ("sase.workspace_provider.registry", "save_registry"),
    "clone_external_repo": (_REGISTRY_IMPL, "clone_external_repo"),
    "create_sdd_remote": (_REGISTRY_IMPL, "create_sdd_remote"),
    "detect_workflow_type": (_REGISTRY_IMPL, "detect_workflow_type"),
    "extract_change_identifier": (
        _REGISTRY_IMPL,
        "extract_change_identifier",
    ),
    "format_commit_description": (
        _REGISTRY_IMPL,
        "format_commit_description",
    ),
    "generate_reviewer_comments_script": (
        _REGISTRY_IMPL,
        "generate_reviewer_comments_script",
    ),
    "generate_submitted_check_script": (
        _REGISTRY_IMPL,
        "generate_submitted_check_script",
    ),
    "get_all_workflow_metadata": (
        _REGISTRY_IMPL,
        "get_all_workflow_metadata",
    ),
    "get_change_label": (_REGISTRY_IMPL, "get_change_label"),
    "get_display_name": (_REGISTRY_IMPL, "get_display_name"),
    "get_display_name_by_vcs": (_REGISTRY_IMPL, "get_display_name_by_vcs"),
    "get_display_name_by_vcs_family": (
        _REGISTRY_IMPL,
        "get_display_name_by_vcs_family",
    ),
    "get_pre_allocated_env_prefix": (
        _REGISTRY_IMPL,
        "get_pre_allocated_env_prefix",
    ),
    "get_sdd_storage_policy_by_vcs": (
        _REGISTRY_IMPL,
        "get_sdd_storage_policy_by_vcs",
    ),
    "get_embedded_vcs_tag_pattern": (
        _REGISTRY_IMPL,
        "get_embedded_vcs_tag_pattern",
    ),
    "get_external_repo_schemes": (
        _REGISTRY_IMPL,
        "get_external_repo_schemes",
    ),
    "get_ref_patterns": (_REGISTRY_IMPL, "get_ref_patterns"),
    "get_vcs_tag_pattern": (_REGISTRY_IMPL, "get_vcs_tag_pattern"),
    "get_workflow_names": (_REGISTRY_IMPL, "get_workflow_names"),
    "get_workspace_directory": (_REGISTRY_IMPL, "get_workspace_directory"),
    "get_workspace_name": (_REGISTRY_IMPL, "get_workspace_name"),
    "list_ref_namespaces": (_REGISTRY_IMPL, "list_ref_namespaces"),
    "list_repo_candidates": (_REGISTRY_IMPL, "list_repo_candidates"),
    "materialize_sdd_store": (_REGISTRY_IMPL, "materialize_sdd_store"),
    "peek_ref": (_REGISTRY_IMPL, "peek_ref"),
    "preflight_sdd_sidecar": (_REGISTRY_IMPL, "preflight_sdd_sidecar"),
    "prepare_mail": (_REGISTRY_IMPL, "prepare_mail"),
    "reset_workflow_metadata_caches": (
        _REGISTRY_IMPL,
        "reset_workflow_metadata_caches",
    ),
    "resolve_ref": (_REGISTRY_IMPL, "resolve_ref"),
    "submit_patch": (_REGISTRY_IMPL, "submit_patch"),
    "supports_reviewer_comments": (
        _REGISTRY_IMPL,
        "supports_reviewer_comments",
    ),
}

__all__ = [
    "AccessKind",
    "CheckoutMarker",
    "ExternalRepoCloneResult",
    "MutationOrigin",
    "OperationContext",
    "WorkspaceOwnershipError",
    "ResolvedRef",
    "SddSidecarPreflight",
    "SddSidecarPreflightStatus",
    "SUBMITTED_CHECK_EXIT_CODE_CLOSED",
    "VcsNamespaceEntry",
    "VcsRefNamespaces",
    "VcsRepoCandidates",
    "VcsRepoEntry",
    "WorkflowMetadata",
    "WorkspaceEntry",
    "WorkspaceHookSpec",
    "WorkspacePluginManager",
    "WorkspaceRegistry",
    "authorize_store_mutation",
    "clone_external_repo",
    "create_sdd_remote",
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
    "get_external_repo_schemes",
    "get_pre_allocated_env_prefix",
    "get_sdd_storage_policy_by_vcs",
    "get_ref_patterns",
    "get_vcs_tag_pattern",
    "get_workflow_names",
    "get_workspace_directory",
    "get_workspace_name",
    "hookimpl",
    "hookspec",
    "list_ref_namespaces",
    "leased_operational_context",
    "list_repo_candidates",
    "load_or_init_registry",
    "materialize_sdd_store",
    "normalize_workspace_num",
    "peek_ref",
    "preflight_sdd_sidecar",
    "prepare_mail",
    "primary_sidecar_sync_context",
    "read_marker",
    "read_only_canonical_context",
    "record_workspace",
    "remove_workspace",
    "reset_workflow_metadata_caches",
    "resolve_consistent_workspace_pair",
    "resolve_ref",
    "resolve_workspace_num_for_dir",
    "save_registry",
    "submit_patch",
    "submit_patch",
    "supports_reviewer_comments",
    "user_directed_context",
    "writable_beads_dir",
    "writable_checkout_dir",
    "writable_kind_root",
    "writable_plans_dir",
    "writable_sidecar_root",
    "write_marker",
]

if TYPE_CHECKING:
    from ._hookspec import (
        SUBMITTED_CHECK_EXIT_CODE_CLOSED,
        ExternalRepoCloneResult,
        ResolvedRef,
        SddSidecarPreflight,
        SddSidecarPreflightStatus,
        VcsNamespaceEntry,
        VcsRefNamespaces,
        VcsRepoCandidates,
        VcsRepoEntry,
        WorkflowMetadata,
        WorkspaceHookSpec,
        hookimpl,
        hookspec,
    )
    from ._plugin_manager import WorkspacePluginManager
    from ._registry import (
        clone_external_repo,
        create_sdd_remote,
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
        get_embedded_vcs_tag_pattern,
        get_external_repo_schemes,
        get_pre_allocated_env_prefix,
        get_ref_patterns,
        get_sdd_storage_policy_by_vcs,
        get_vcs_tag_pattern,
        get_workflow_names,
        get_workspace_directory,
        get_workspace_name,
        list_ref_namespaces,
        list_repo_candidates,
        materialize_sdd_store,
        peek_ref,
        preflight_sdd_sidecar,
        prepare_mail,
        reset_workflow_metadata_caches,
        resolve_ref,
        submit_patch,
        supports_reviewer_comments,
    )
    from .lookup import (
        resolve_consistent_workspace_pair,
        resolve_workspace_num_for_dir,
    )
    from .marker import (
        CheckoutMarker,
        find_marker_from_cwd,
        read_marker,
        write_marker,
    )
    from .ownership import (
        AccessKind,
        MutationOrigin,
        OperationContext,
        WorkspaceOwnershipError,
        authorize_store_mutation,
        leased_operational_context,
        normalize_workspace_num,
        primary_sidecar_sync_context,
        read_only_canonical_context,
        user_directed_context,
        writable_beads_dir,
        writable_checkout_dir,
        writable_kind_root,
        writable_plans_dir,
        writable_sidecar_root,
    )
    from .registry import (
        WorkspaceEntry,
        WorkspaceRegistry,
        load_or_init_registry,
        record_workspace,
        remove_workspace,
        save_registry,
    )


def __getattr__(name: str) -> object:
    return lazy_getattr(__name__, globals(), _LAZY_EXPORTS, name)


def __dir__() -> list[str]:
    return lazy_dir(globals(), _LAZY_EXPORTS)
