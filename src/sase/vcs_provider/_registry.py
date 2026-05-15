"""Factory and auto-detection for VCS providers."""

import importlib.metadata
import os
import subprocess

import pluggy

from ._base import VCSProvider
from ._errors import VCSProviderNotFoundError
from ._hookspec import VCSHookSpec
from ._plugin_manager import VCSPluginManager
from .config import get_vcs_provider_config


def _build_classification_pm() -> pluggy.PluginManager:
    """Build a :class:`pluggy.PluginManager` with all ``sase_vcs`` plugins.

    Shared by :func:`detect_vcs` and :func:`_classify_via_plugins`.
    """
    pm = pluggy.PluginManager("sase_vcs")
    pm.add_hookspecs(VCSHookSpec)
    for ep in importlib.metadata.entry_points(group="sase_vcs"):
        plugin_class = ep.load()
        pm.register(plugin_class())
    return pm


def _classify_git_repo(git_dir: str, pm: pluggy.PluginManager | None = None) -> str:
    """Classify a git repo by consulting plugins, then falling back to URL heuristics.

    Resolution order:

    1. Ask all registered ``sase_vcs`` plugins via the
       :meth:`~VCSHookSpec.vcs_classify_repo` hook.  The first plugin to
       return a non-``None`` name wins.
    2. Fall back to URL-based heuristics: any resolvable remote URL
       (local or hosted) → ``"bare_git"``.

    Args:
        git_dir: A directory inside the git working tree (used as *cwd*
            for ``git config``).
        pm: Optional pre-built plugin manager (avoids duplicate creation).

    Returns:
        A VCS provider name (e.g. ``"github"``, ``"bare_git"``).
    """
    # 1. Try plugin-based classification
    plugin_result = _classify_via_plugins(git_dir, pm)
    if plugin_result is not None:
        return plugin_result

    # 2. Fall back to URL heuristics
    return _classify_by_url(git_dir)


def _classify_via_plugins(
    git_dir: str, pm: pluggy.PluginManager | None = None
) -> str | None:
    """Ask all ``sase_vcs`` entry-point plugins to classify the repo.

    Returns the first non-``None`` result, or ``None`` if no plugin
    claims the repo.
    """
    if pm is None:
        pm = _build_classification_pm()
    result: str | None = pm.hook.vcs_classify_repo(git_dir=git_dir)
    return result


def _classify_by_url(git_dir: str) -> str:
    """Classify a git repo using its origin remote URL.

    Returns ``"bare_git"`` for any resolvable remote URL (local path or
    hosted) when no plugin claimed the repo.  Only raises
    :class:`VCSProviderNotFoundError` for truly indeterminate states
    (cannot read origin, no origin configured).
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
        raise VCSProviderNotFoundError(
            git_dir,
            "Could not determine remote URL. Install a VCS plugin "
            "(e.g. sase-github) for this repository.",
        ) from None

    if result.returncode != 0:
        raise VCSProviderNotFoundError(
            git_dir,
            "No remote 'origin' configured. Install a VCS plugin "
            "(e.g. sase-github) for this repository.",
        )

    url = result.stdout.strip()
    if not url:
        raise VCSProviderNotFoundError(
            git_dir,
            "Remote 'origin' URL is empty. Install a VCS plugin "
            "(e.g. sase-github) for this repository.",
        )
    return "bare_git"


def detect_vcs(cwd: str) -> str | None:
    """Walk up from *cwd* looking for VCS markers or ``.git``.

    Uses plugins via :meth:`~VCSHookSpec.vcs_detect_repo_type` to detect
    non-git VCS types (e.g. ``.hg/``), then falls back to ``.git`` detection.

    Returns the provider name (``"github"``, ``"bare_git"``, ``"hg"``)
    or ``None``.

    Note: ``.git`` is checked with ``os.path.exists`` rather than
    ``os.path.isdir`` because some git setups (e.g. submodules) use a
    ``.git`` *file* (containing a ``gitdir:`` pointer) instead of a directory.
    """
    pm = _build_classification_pm()
    directory = os.path.abspath(cwd)
    while True:
        # 1. Ask plugins to detect their VCS markers
        repo_type: str | None = pm.hook.vcs_detect_repo_type(directory=directory)
        if repo_type is not None:
            return repo_type
        # 2. Check for .git
        if os.path.exists(os.path.join(directory, ".git")):
            return _classify_git_repo(directory, pm)
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

    All providers are routed through the pluggy plugin system via
    entry-point discovery.

    Raises:
        VCSProviderNotFoundError: If no VCS directory is found or no
            provider is registered for the detected VCS type.
    """
    vcs_name = _resolve_vcs_name(cwd)
    if vcs_name is None:
        raise VCSProviderNotFoundError(cwd)

    return _create_provider_for(vcs_name, cwd)


def _find_plugin_class(vcs_name: str) -> type | None:
    """Look up a VCS plugin class by name from ``sase_vcs`` entry points.

    Args:
        vcs_name: The entry-point name to find (e.g. ``"github"``).

    Returns:
        The plugin class, or ``None`` if no matching entry point exists.
    """
    for ep in importlib.metadata.entry_points(group="sase_vcs"):
        if ep.name == vcs_name:
            return ep.load()  # type: ignore[no-any-return]
    return None


def _create_provider_for(vcs_name: str, cwd: str) -> VCSPluginManager:
    """Create a :class:`VCSPluginManager` for *vcs_name* via entry points.

    Args:
        vcs_name: Provider name (e.g. ``"github"``, ``"hg"``, ``"bare_git"``).
        cwd: Working directory (used only for the error message).

    Raises:
        VCSProviderNotFoundError: If no entry point matches *vcs_name*.
    """
    pm = pluggy.PluginManager("sase_vcs")
    pm.add_hookspecs(VCSHookSpec)

    plugin_class = _find_plugin_class(vcs_name)
    if plugin_class is None:
        raise VCSProviderNotFoundError(
            cwd,
            f"No VCS plugin found for '{vcs_name}'. "
            f"Install the plugin package that provides a '{vcs_name}' "
            f"entry point in the 'sase_vcs' group.",
        )

    pm.register(plugin_class())
    return VCSPluginManager(pm)
