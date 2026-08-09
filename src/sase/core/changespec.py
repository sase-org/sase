"""Legacy ChangeSpec compatibility facade for :mod:`sase.core.patch`."""

from typing import TYPE_CHECKING

from sase.core.patch import (
    ensure_project_prefix,
    get_next_suffix_number,
    get_workspace_directory_for_patch,
    has_suffix,
    patch_name_to_branch,
    patch_name_to_branch_with_suffix,
    patch_names_match,
    strip_reverted_suffix,
)

if TYPE_CHECKING:
    from sase.ace.patch import Patch


changespec_names_match = patch_names_match
changespec_name_to_branch = patch_name_to_branch
changespec_name_to_branch_with_suffix = patch_name_to_branch_with_suffix


def get_workspace_directory_for_changespec(changespec: "Patch") -> str | None:
    """Legacy alias for :func:`sase.core.patch.get_workspace_directory_for_patch`."""
    return get_workspace_directory_for_patch(changespec)


__all__ = [
    "changespec_name_to_branch",
    "changespec_name_to_branch_with_suffix",
    "changespec_names_match",
    "ensure_project_prefix",
    "get_next_suffix_number",
    "get_workspace_directory_for_changespec",
    "has_suffix",
    "strip_reverted_suffix",
]
