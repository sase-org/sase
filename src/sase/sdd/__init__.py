"""SDD (Spec-Driven Development) subpackage.

Groups SDD file operations and bead initialization.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from sase._lazy_exports import lazy_dir, lazy_getattr

_LAZY_EXPORTS = {
    "init_beads": ("sase.sdd.beads", "init_beads"),
    "ensure_beads_initialized": (
        "sase.sdd.beads",
        "ensure_beads_initialized",
    ),
    "dry_expand_embedded_workflows": (
        "sase.sdd.files",
        "dry_expand_embedded_workflows",
    ),
    "ensure_bare_git_sdd_initialized": (
        "sase.sdd.files",
        "ensure_bare_git_sdd_initialized",
    ),
    "ensure_sdd_initialized": ("sase.sdd.files", "ensure_sdd_initialized"),
    "expected_sdd_directory_map": (
        "sase.sdd.files",
        "expected_sdd_directory_map",
    ),
    "expected_sdd_directory_readmes": (
        "sase.sdd.files",
        "expected_sdd_directory_readmes",
    ),
    "expected_sdd_generated_paths": (
        "sase.sdd.files",
        "expected_sdd_generated_paths",
    ),
    "get_primary_workspace_dir": (
        "sase.sdd.files",
        "get_primary_workspace_dir",
    ),
    "is_sdd_internal_path": ("sase.sdd.files", "is_sdd_internal_path"),
    "commit_sdd_files": ("sase.sdd.files", "commit_sdd_files"),
    "commit_sdd_store_files": ("sase.sdd.files", "commit_sdd_store_files"),
    "expand_prompt_for_spec": ("sase.sdd.files", "expand_prompt_for_spec"),
    "set_prompt_qa": ("sase.sdd.files", "set_prompt_qa"),
    "update_prompt_with_qa": ("sase.sdd.files", "update_prompt_with_qa"),
    "update_spec_with_qa": ("sase.sdd.files", "update_spec_with_qa"),
    "write_sdd_readme": ("sase.sdd.files", "write_sdd_readme"),
    "write_sdd_files": ("sase.sdd.files", "write_sdd_files"),
    "write_sdd_spec": ("sase.sdd.files", "write_sdd_spec"),
    "SddInitOutcome": ("sase.sdd.store", "SddInitOutcome"),
    "SddSidecar": ("sase.sdd.store", "SddSidecar"),
    "SddStore": ("sase.sdd.store", "SddStore"),
    "SddStoreRecord": ("sase.sdd.store", "SddStoreRecord"),
    "SddMaterializationError": (
        "sase.sdd.store",
        "SddMaterializationError",
    ),
    "create_and_materialize_sdd_store": (
        "sase.sdd.store",
        "create_and_materialize_sdd_store",
    ),
    "delete_sdd_store_record": (
        "sase.sdd.store",
        "delete_sdd_store_record",
    ),
    "ensure_workspace_sdd_clone": (
        "sase.sdd.store",
        "ensure_workspace_sdd_clone",
    ),
    "ensure_sdd_kind_clone": ("sase.sdd.store", "ensure_sdd_kind_clone"),
    "materialized_sdd_clone": ("sase.sdd.store", "materialized_sdd_clone"),
    "materialize_sdd_store": ("sase.sdd.store", "materialize_sdd_store"),
    "normalize_sdd_store_record": (
        "sase.sdd.store",
        "normalize_sdd_store_record",
    ),
    "read_sdd_store_record": ("sase.sdd.store", "read_sdd_store_record"),
    "resolve_sdd_dir": ("sase.sdd.store", "resolve_sdd_dir"),
    "resolve_sdd_kind_dir": ("sase.sdd.store", "resolve_sdd_kind_dir"),
    "resolve_sdd_store": ("sase.sdd.store", "resolve_sdd_store"),
    "write_sdd_store_record": ("sase.sdd.store", "write_sdd_store_record"),
}

__all__ = [
    "dry_expand_embedded_workflows",
    "ensure_bare_git_sdd_initialized",
    "ensure_sdd_initialized",
    "expected_sdd_directory_map",
    "expected_sdd_directory_readmes",
    "expected_sdd_generated_paths",
    "get_primary_workspace_dir",
    "is_sdd_internal_path",
    "init_beads",
    "commit_sdd_files",
    "commit_sdd_store_files",
    "ensure_beads_initialized",
    "expand_prompt_for_spec",
    "set_prompt_qa",
    "update_prompt_with_qa",
    "update_spec_with_qa",
    "write_sdd_readme",
    "write_sdd_files",
    "write_sdd_spec",
    "SddInitOutcome",
    "SddSidecar",
    "SddStore",
    "SddStoreRecord",
    "SddMaterializationError",
    "create_and_materialize_sdd_store",
    "delete_sdd_store_record",
    "ensure_workspace_sdd_clone",
    "ensure_sdd_kind_clone",
    "materialized_sdd_clone",
    "materialize_sdd_store",
    "normalize_sdd_store_record",
    "read_sdd_store_record",
    "resolve_sdd_dir",
    "resolve_sdd_kind_dir",
    "resolve_sdd_store",
    "write_sdd_store_record",
]

if TYPE_CHECKING:
    from sase.sdd.beads import ensure_beads_initialized, init_beads
    from sase.sdd.files import (
        commit_sdd_files,
        commit_sdd_store_files,
        dry_expand_embedded_workflows,
        ensure_bare_git_sdd_initialized,
        ensure_sdd_initialized,
        expected_sdd_directory_map,
        expected_sdd_directory_readmes,
        expected_sdd_generated_paths,
        expand_prompt_for_spec,
        get_primary_workspace_dir,
        is_sdd_internal_path,
        set_prompt_qa,
        update_prompt_with_qa,
        update_spec_with_qa,
        write_sdd_files,
        write_sdd_readme,
        write_sdd_spec,
    )
    from sase.sdd.store import (
        SddInitOutcome,
        SddMaterializationError,
        SddSidecar,
        SddStore,
        SddStoreRecord,
        create_and_materialize_sdd_store,
        delete_sdd_store_record,
        ensure_sdd_kind_clone,
        ensure_workspace_sdd_clone,
        materialize_sdd_store,
        materialized_sdd_clone,
        normalize_sdd_store_record,
        read_sdd_store_record,
        resolve_sdd_dir,
        resolve_sdd_kind_dir,
        resolve_sdd_store,
        write_sdd_store_record,
    )


def __getattr__(name: str) -> object:
    return lazy_getattr(__name__, globals(), _LAZY_EXPORTS, name)


def __dir__() -> list[str]:
    return lazy_dir(globals(), _LAZY_EXPORTS)
