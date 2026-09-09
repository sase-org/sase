"""Generic workspace utilities extracted from gh_workspace.py.

Provides project-file helpers (parse/set WORKSPACE_DIR), generic git
utilities (default branch, cloning), and legacy VCS-type detection that
will eventually delegate to workspace provider plugins.

Implementation lives in the ``_utils_*`` modules; this module is the
public import path and re-exports the documented helpers.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

from sase.workspace_provider._utils_checkout import (
    ensure_git_clone_at,
    ensure_workspace_checkout,
    parse_bare_repo_dir,
    parse_workspace_dir,
    set_workspace_dir,
)
from sase.workspace_provider._utils_git import (
    get_default_branch,
    non_interactive_git_env,
)
from sase.workspace_provider._utils_origin import (
    reconcile_managed_checkout_origin,
)

# Test doubles patch ``sase.workspace_provider.utils.subprocess.run``.


class ProjectProviderMismatchError(ValueError):
    """A VCS ref's workflow tag doesn't match its project's actual provider."""


# Re-export Path for convenience (used by callers that need projects_base)
__all__ = [
    "Path",
    "ProjectProviderMismatchError",
    "ensure_git_clone_at",
    "ensure_workspace_checkout",
    "get_default_branch",
    "non_interactive_git_env",
    "parse_bare_repo_dir",
    "parse_workspace_dir",
    "reconcile_managed_checkout_origin",
    "set_workspace_dir",
]
