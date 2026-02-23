"""Factory and auto-detection for VCS providers."""

import os
import subprocess

import pluggy

from ._base import VCSProvider
from ._errors import VCSProviderNotFoundError
from ._hookspec import VCSHookSpec
from ._plugin_manager import VCSPluginManager
from .config import get_vcs_provider_config

# provider-name → provider-class (used for non-plugin providers during migration)
_PROVIDERS: dict[str, type[VCSProvider]] = {}


def register_provider(name: str, cls: type[VCSProvider]) -> None:
    """Register a VCS provider class under *name* (e.g. ``"hg"``)."""
    _PROVIDERS[name] = cls


def _classify_git_repo(git_dir: str) -> str:
    """Classify a git repo as ``"github"`` or ``"bare_git"``.

    Checks the origin remote URL.  If it is a local filesystem path
    (not ``http(s)://``, ``git@``, or ``ssh://``) the repo is considered
    bare-git backed.  Otherwise it is treated as GitHub-hosted.

    Args:
        git_dir: A directory inside the git working tree (used as *cwd*
            for ``git config``).

    Returns:
        ``"github"`` or ``"bare_git"``.
    """
    try:
        result = subprocess.run(
            ["git", "config", "--get", "remote.origin.url"],
            cwd=git_dir,
            capture_output=True,
            text=True,
            check=False,
            timeout=10,
        )
    except (subprocess.TimeoutExpired, FileNotFoundError, OSError):
        return "github"

    if result.returncode != 0:
        return "github"

    url = result.stdout.strip()
    if url and not url.startswith(("http://", "https://", "git@", "ssh://")):
        return "bare_git"
    return "github"


def detect_vcs(cwd: str) -> str | None:
    """Walk up from *cwd* looking for ``.hg/`` or ``.git``.

    Returns the provider name (``"github"``, ``"bare_git"``, ``"hg"``)
    or ``None``.

    Note: ``.git`` is checked with ``os.path.exists`` rather than
    ``os.path.isdir`` because some git setups (e.g. submodules) use a
    ``.git`` *file* (containing a ``gitdir:`` pointer) instead of a directory.
    """
    directory = os.path.abspath(cwd)
    while True:
        if os.path.isdir(os.path.join(directory, ".hg")):
            return "hg"
        if os.path.exists(os.path.join(directory, ".git")):
            return _classify_git_repo(directory)
        parent = os.path.dirname(directory)
        if parent == directory:
            break
        directory = parent
    return None


def detect_vcs_family(cwd: str) -> str | None:
    """Like :func:`detect_vcs` but collapses git variants to ``"git"``.

    Returns ``"git"``, ``"hg"``, or ``None``.
    """
    vcs = detect_vcs(cwd)
    if vcs in ("github", "bare_git"):
        return "git"
    return vcs


def _resolve_vcs_name(cwd: str) -> str | None:
    """Determine the VCS provider name to use.

    Resolution order:
    1. Env var ``SASE_VCS_PROVIDER`` (if set and not ``"auto"``)
    2. Config ``vcs_provider.provider`` from sase.yml (if set and not ``"auto"``)
    3. ``detect_vcs(cwd)`` (auto-detection)

    Legacy ``"git"`` values from env/config are re-classified via
    :func:`_classify_git_repo`.
    """
    # 1. Environment variable override
    env_val = os.environ.get("SASE_VCS_PROVIDER")
    if env_val and env_val != "auto":
        if env_val == "git":
            return _classify_git_repo(cwd)
        return env_val

    # 2. Config file override (only if env var didn't short-circuit)
    if not env_val:
        config = get_vcs_provider_config()
        config_provider = config.get("provider")
        if config_provider and config_provider != "auto":
            if config_provider == "git":
                return _classify_git_repo(cwd)
            return config_provider

    # 3. Auto-detection
    return detect_vcs(cwd)


def get_vcs_provider(cwd: str) -> VCSProvider:
    """Return a :class:`VCSProvider` instance for *cwd*.

    Uses :func:`_resolve_vcs_name` to determine the provider, which
    checks env var, config, and auto-detection in that order.

    All providers are routed through the pluggy plugin system.

    Raises:
        VCSProviderNotFoundError: If no VCS directory is found or no
            provider is registered for the detected VCS type.
    """
    vcs_name = _resolve_vcs_name(cwd)
    if vcs_name is None:
        raise VCSProviderNotFoundError(cwd)

    if vcs_name == "hg":
        return _create_hg_plugin_provider()
    if vcs_name == "github":
        return _create_github_plugin_provider()
    if vcs_name == "bare_git":
        return _create_bare_git_plugin_provider()

    # Legacy fallback for unknown provider names from env/config overrides
    _ensure_providers_loaded()
    cls = _PROVIDERS.get(vcs_name)
    if cls is None:
        raise VCSProviderNotFoundError(cwd)
    return cls()


def _create_hg_plugin_provider() -> VCSPluginManager:
    """Create a :class:`VCSPluginManager` backed by :class:`HgPlugin`."""
    from .plugins.hg import HgPlugin

    pm = pluggy.PluginManager("sase_vcs")
    pm.add_hookspecs(VCSHookSpec)
    pm.register(HgPlugin())
    return VCSPluginManager(pm)


def _create_github_plugin_provider() -> VCSPluginManager:
    """Create a :class:`VCSPluginManager` backed by :class:`GitHubPlugin`."""
    from .plugins.github import GitHubPlugin

    pm = pluggy.PluginManager("sase_vcs")
    pm.add_hookspecs(VCSHookSpec)
    pm.register(GitHubPlugin())
    return VCSPluginManager(pm)


def _create_bare_git_plugin_provider() -> VCSPluginManager:
    """Create a :class:`VCSPluginManager` backed by :class:`BareGitPlugin`."""
    from .plugins.bare_git import BareGitPlugin

    pm = pluggy.PluginManager("sase_vcs")
    pm.add_hookspecs(VCSHookSpec)
    pm.register(BareGitPlugin())
    return VCSPluginManager(pm)


def _ensure_providers_loaded() -> None:
    """Import provider modules so they self-register."""
    if _PROVIDERS:
        return
    # Import triggers register_provider() at module level
    from . import _git as _git  # noqa: F401
    from . import _hg as _hg  # noqa: F401
