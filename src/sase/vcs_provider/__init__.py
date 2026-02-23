"""VCS provider abstraction layer.

Usage::

    from sase.vcs_provider import get_vcs_provider

    provider = get_vcs_provider(workspace_dir)
    success, error = provider.checkout("my_branch", workspace_dir)
"""

from ._base import VCSProvider
from ._command_runner import CommandRunner
from ._errors import VCSOperationError, VCSProviderNotFoundError
from ._hookspec import VCSHookSpec, hookimpl, hookspec
from ._plugin_manager import VCSPluginManager
from ._registry import detect_vcs, get_vcs_provider, register_provider
from .config import get_workspace_root

VCS_DEFAULT_REVISION = "__vcs_default__"

__all__ = [
    "CommandRunner",
    "VCS_DEFAULT_REVISION",
    "VCSHookSpec",
    "VCSOperationError",
    "VCSPluginManager",
    "VCSProvider",
    "VCSProviderNotFoundError",
    "detect_vcs",
    "get_vcs_provider",
    "get_workspace_root",
    "hookimpl",
    "hookspec",
    "register_provider",
]
