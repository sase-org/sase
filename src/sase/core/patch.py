"""Patch name manipulation utilities.

The legacy implementation lives in :mod:`sase.core.changespec`; this module
exposes canonical Patch names while keeping the old import path working.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from .changespec import (
    changespec_name_to_branch,
    changespec_name_to_branch_with_suffix,
    changespec_names_match,
    ensure_project_prefix,
    get_next_suffix_number,
    get_workspace_directory_for_changespec,
    has_suffix,
    strip_reverted_suffix,
)

if TYPE_CHECKING:
    from sase.ace.patch import Patch

patch_name_to_branch = changespec_name_to_branch
patch_name_to_branch_with_suffix = changespec_name_to_branch_with_suffix
patch_names_match = changespec_names_match


def get_workspace_directory_for_patch(patch: Patch) -> str | None:
    """Get the workspace directory for a Patch."""
    return get_workspace_directory_for_changespec(patch)


__all__ = [
    "ensure_project_prefix",
    "get_next_suffix_number",
    "get_workspace_directory_for_patch",
    "has_suffix",
    "patch_name_to_branch",
    "patch_name_to_branch_with_suffix",
    "patch_names_match",
    "strip_reverted_suffix",
]
