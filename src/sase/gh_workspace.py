"""GitHub workspace management — backward-compat re-exports.

The canonical GitHub-specific code has moved to
:mod:`sase_github.workspace_plugin`.  Generic utilities live in
:mod:`sase.workspace_utils`.  This module re-exports them for backward
compatibility.
"""

# Re-export generic utilities from workspace_utils for backward compat.
from sase.workspace_utils import (
    detect_vcs_type_for_project,
    ensure_git_clone,
    get_cl_field_label,
    get_default_branch,
    get_git_clone_dir,
    parse_workspace_dir,
    set_workspace_dir,
)

__all__ = [
    "detect_vcs_type_for_project",
    "ensure_git_clone",
    "get_cl_field_label",
    "get_default_branch",
    "get_git_clone_dir",
    "parse_workspace_dir",
    "set_workspace_dir",
]
