"""Compatibility facade for SDD file operations.

The implementation is split by responsibility across sibling modules. This
module keeps the historical ``sase.sdd.files`` import and monkeypatch surface
stable for callers and tests.
"""

from datetime import datetime
from pathlib import Path

from sase.sdd._commit import (
    SddGitCommandTimeout,
    changed_sdd_files as _changed_sdd_files,
    commit_bare_git_sdd_init_paths as _commit_bare_git_sdd_init_paths,
    commit_sdd_files,
    commit_sdd_store_files,
    ensure_bare_git_sdd_initialized as _ensure_bare_git_sdd_initialized,
    git_toplevel as _git_toplevel,
    is_local_bare_git_workspace as _is_local_bare_git_workspace,
    normalize_sdd_commit_pathspecs as _normalize_sdd_commit_pathspecs,
    relative_git_pathspecs as _relative_git_pathspecs,
)
from sase.sdd._expand import dry_expand_embedded_workflows, expand_prompt_for_spec
from sase.sdd._init_files import (
    SDD_COMPANION_DIRECTORY_MAP_FILENAMES,
    SDD_COMPANION_KINDS,
    SDD_COMPANION_README_CONTENT,
    SDD_DIRECTORY_MAP_FILENAME,
    SDD_DIRECTORY_MAP_RELATIVE_PATH,
    SDD_DIRECTORY_README_CONTENT,
    SDD_README_CONTENT,
    ensure_sdd_companion_initialized,
    expected_sdd_companion_files,
    expected_sdd_directory_map,
    expected_sdd_directory_readmes,
    expected_sdd_generated_paths,
    expected_sdd_readme,
    expected_sdd_text_files as _expected_sdd_text_files,
    plan_sdd_companion_init_actions,
    plan_sdd_init_actions,
    planned_bytes_operation as _planned_bytes_operation,
    planned_text_operation as _planned_text_operation,
    read_sdd_directory_map_bytes as _read_sdd_directory_map_bytes,
    sdd_init_detail_for_path as _sdd_init_detail_for_path,
    write_sdd_directory_map as _write_sdd_directory_map,
    write_sdd_readme,
)
from sase.sdd._paths import (
    find_sdd_file,
    get_primary_workspace_dir as _get_primary_workspace_dir,
    get_yyyymm as _get_yyyymm,
    is_sdd_internal_path,
    looks_like_sdd_root as _looks_like_sdd_root,
    resolve_primary_from_project as _resolve_primary_from_project_impl,
    resolve_sdd_asset_path as _resolve_sdd_asset_path,
    resolve_sdd_readme_path as _resolve_sdd_readme_path,
    sdd_kind_roots as _sdd_kind_roots,
)
from sase.sdd._types import (
    SddExpectedBytesFile,
    SddExpectedTextFile,
    SddInitAction,
    SddInitOperation,
)
from sase.sdd._write import (
    set_prompt_qa,
    sdd_link_path as _sdd_link_path,
    strip_qa_block as _strip_qa_block,
    update_prompt_with_qa,
    update_spec_with_qa,
    write_sdd_files as _write_sdd_files,
)

_SddExpectedTextFile = SddExpectedTextFile
_SddExpectedBytesFile = SddExpectedBytesFile
_SddInitAction = SddInitAction


def get_yyyymm(dt: datetime | None = None) -> str:
    """Return a YYYYMM string for SDD subdirectory organization."""
    return _get_yyyymm(dt)


def get_primary_workspace_dir(workspace_dir: str, workspace_num: int) -> str:
    """Derive primary workspace dir from current workspace."""
    return _get_primary_workspace_dir(
        workspace_dir,
        workspace_num,
        project_home=Path.home(),
    )


def _resolve_primary_from_project(workspace_dir: str) -> str | None:
    """Resolve primary workspace from the project's WORKSPACE_DIR field."""
    return _resolve_primary_from_project_impl(workspace_dir, project_home=Path.home())


def ensure_sdd_initialized(
    path: str | Path | None = None, *, cwd: Path | None = None
) -> tuple[Path, ...]:
    """Create or refresh generated SDD guide files only when they drift.

    Returns the generated paths that were missing or stale before the refresh.
    A current SDD tree returns an empty tuple and performs no writes.
    """
    path_arg = str(path) if path is not None else None
    actions = plan_sdd_init_actions(path_arg, cwd=cwd)
    if not actions:
        return ()
    write_sdd_readme(path_arg, cwd=cwd)
    return tuple(action.path for action in actions)


def ensure_bare_git_sdd_initialized(
    workspace_dir: str | Path,
    *,
    commit: bool = True,
    push: bool = False,
    raise_on_error: bool = False,
) -> tuple[Path, ...]:
    """Ensure generated SDD init files exist for a local bare-git checkout."""
    return _ensure_bare_git_sdd_initialized(
        workspace_dir,
        commit=commit,
        push=push,
        raise_on_error=raise_on_error,
        initializer=ensure_sdd_initialized,
    )


def write_sdd_files(
    sdd_dir: Path,
    plan_name: str,
    prompt_content: str,
    plan_file: str,
    *,
    plan_tier: str = "tale",
    plans_root: Path | None = None,
) -> tuple[Path, Path]:
    """Write a prompt and tiered plan under canonical directories.

    Returns (prompt_path, plan_path).
    """
    return _write_sdd_files(
        sdd_dir,
        plan_name,
        prompt_content,
        plan_file,
        plan_tier=plan_tier,
        plans_root=plans_root,
        yyyymm=get_yyyymm(),
    )


__all__ = [
    "SDD_COMPANION_DIRECTORY_MAP_FILENAMES",
    "SDD_COMPANION_KINDS",
    "SDD_COMPANION_README_CONTENT",
    "SDD_DIRECTORY_MAP_FILENAME",
    "SDD_DIRECTORY_MAP_RELATIVE_PATH",
    "SDD_DIRECTORY_README_CONTENT",
    "SDD_README_CONTENT",
    "SddExpectedBytesFile",
    "SddExpectedTextFile",
    "SddGitCommandTimeout",
    "SddInitAction",
    "SddInitOperation",
    "commit_sdd_files",
    "commit_sdd_store_files",
    "dry_expand_embedded_workflows",
    "ensure_bare_git_sdd_initialized",
    "ensure_sdd_companion_initialized",
    "ensure_sdd_initialized",
    "expected_sdd_directory_map",
    "expected_sdd_companion_files",
    "expected_sdd_directory_readmes",
    "expected_sdd_generated_paths",
    "expected_sdd_readme",
    "expand_prompt_for_spec",
    "find_sdd_file",
    "get_primary_workspace_dir",
    "get_yyyymm",
    "is_sdd_internal_path",
    "plan_sdd_init_actions",
    "plan_sdd_companion_init_actions",
    "set_prompt_qa",
    "update_prompt_with_qa",
    "update_spec_with_qa",
    "write_sdd_files",
    "write_sdd_readme",
    "_SddExpectedBytesFile",
    "_SddExpectedTextFile",
    "_SddInitAction",
    "_changed_sdd_files",
    "_commit_bare_git_sdd_init_paths",
    "_expected_sdd_text_files",
    "_git_toplevel",
    "_is_local_bare_git_workspace",
    "_looks_like_sdd_root",
    "_normalize_sdd_commit_pathspecs",
    "_planned_bytes_operation",
    "_planned_text_operation",
    "_read_sdd_directory_map_bytes",
    "_relative_git_pathspecs",
    "_resolve_primary_from_project",
    "_resolve_sdd_asset_path",
    "_resolve_sdd_readme_path",
    "_sdd_init_detail_for_path",
    "_sdd_kind_roots",
    "_sdd_link_path",
    "_strip_qa_block",
    "_write_sdd_directory_map",
]
