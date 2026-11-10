"""Compatibility facade for workspace checkout helpers.

Implementation is split across private modules; public names remain available
from this original import path.
"""

from sase.workspace_provider._utils_checkout_clone import ensure_git_clone_at
from sase.workspace_provider._utils_checkout_workspace import (
    ensure_workspace_checkout,
    recreate_managed_workspace,
)
from sase.workspace_provider._utils_project_file import (
    parse_bare_repo_dir,
    parse_workspace_dir,
    set_workspace_dir,
)

__all__ = [
    "ensure_git_clone_at",
    "ensure_workspace_checkout",
    "parse_bare_repo_dir",
    "parse_workspace_dir",
    "recreate_managed_workspace",
    "set_workspace_dir",
]
