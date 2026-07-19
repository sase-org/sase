"""First-class workspace path resolution (Phase 1 of sase-3p).

``WorkspaceStore`` exposes the layout decisions that were previously
hard-coded as ``primary_<num>`` string concatenation in
``_get_git_clone_dir()``.  It supports three root policies — ``adjacent``
(legacy parity), ``xdg-state``, and absolute paths — plus a
``SASE_WORKSPACE_ROOT`` environment override.

This phase is compatibility-only: nothing in the runtime calls into the
store yet.  Later phases route provider materialization, allocation, and
the ``sase workspace`` CLI through this surface.
"""

import hashlib
import os
import re
import subprocess
import sys
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal


WORKSPACE_ROOT_ENV = "SASE_WORKSPACE_ROOT"
DEFAULT_WORKSPACE_ROOT = "xdg-state"

# Identity for the user's checkout under the WorkspaceStore.  Legacy code
# still uses ``1`` to mean "primary" — adjacent parity preserves that.
PRIMARY_WORKSPACE_NUM = 0
LEGACY_PRIMARY_WORKSPACE_NUM = 1

RootPolicy = Literal["adjacent", "xdg-state", "absolute"]


@dataclass(frozen=True)
class WorkspacePath:
    """Resolved on-disk identity of a single workspace checkout."""

    project_key: str
    workspace_num: int
    root_dir: str
    checkout_dir: str
    materialization: str
    generation: int = 0
    display_label: str = ""


_SLUG_INVALID_CHARS = re.compile(r"[^A-Za-z0-9._-]+")


def _slugify(value: str) -> str:
    """Make *value* safe for use as a single path component."""
    cleaned = _SLUG_INVALID_CHARS.sub("_", value).strip("_")
    return cleaned or "unnamed"


def _sanitize_project_key_component(value: str) -> str:
    """Return a safe project-key path component."""
    raw = value.strip()
    if raw in {"", ".", ".."}:
        raise ValueError(f"Invalid workspace.project_key component: {value!r}")

    cleaned = _SLUG_INVALID_CHARS.sub("_", raw).strip("_")
    if cleaned in {"", ".", ".."}:
        raise ValueError(f"Invalid workspace.project_key component: {value!r}")
    return cleaned


def _sanitize_project_key(value: str) -> str:
    """Sanitize slash-separated project-key components.

    Project keys may intentionally contain ``/`` to create nested roots
    such as ``sase-org/sase``.  Each component is slugified separately so
    invalid characters cannot collapse path boundaries.
    """
    return "/".join(_sanitize_project_key_component(part) for part in value.split("/"))


def _normalize_git_url(url: str) -> str | None:
    """Reduce a git remote URL to a stable ``<host>/<owner>/<repo>`` form."""
    url = url.strip()
    if not url:
        return None

    # SSH form: ``git@host:owner/repo(.git)?``
    m = re.match(r"^[^@\s]+@([^:]+):(.+?)(?:\.git)?/?$", url)
    if m:
        return f"{m.group(1)}/{m.group(2)}"

    # URL form: ``scheme://[user@]host[:port]/path``
    m = re.match(
        r"^[a-zA-Z][a-zA-Z0-9+.-]*://(?:[^@/]+@)?([^/:]+)(?::\d+)?/(.+?)(?:\.git)?/?$",
        url,
    )
    if m:
        return f"{m.group(1)}/{m.group(2)}"

    return None


def _list_git_remote_urls(primary_workspace_dir: str) -> list[str]:
    """Return unique remote URLs configured in *primary_workspace_dir*.

    Returns an empty list on any failure or when the directory has no
    remotes (not a git repo, missing git, etc.).
    """
    if not os.path.isdir(primary_workspace_dir):
        return []
    try:
        result = subprocess.run(
            ["git", "remote", "-v"],
            cwd=primary_workspace_dir,
            capture_output=True,
            text=True,
            check=False,
        )
    except (OSError, FileNotFoundError):
        return []

    if result.returncode != 0:
        return []

    urls: list[str] = []
    seen: set[str] = set()
    for line in result.stdout.splitlines():
        parts = line.split()
        if len(parts) < 2:
            continue
        url = parts[1]
        if url not in seen:
            seen.add(url)
            urls.append(url)
    return urls


def _project_key_from_path(primary_workspace_dir: str) -> str:
    """Fallback project key: basename plus a short content hash."""
    abs_path = os.path.abspath(primary_workspace_dir).rstrip("/")
    basename = os.path.basename(abs_path) or "workspace"
    digest = hashlib.sha256(abs_path.encode("utf-8")).hexdigest()[:8]
    return f"{_slugify(basename)}-{digest}"


def _derive_project_key(
    primary_workspace_dir: str,
    *,
    explicit: str | None = None,
) -> str:
    """Derive a stable project key for namespacing managed workspaces.

    Resolution order:

    1. ``explicit`` (e.g. ``workspace.project_key``) when non-empty.
    2. Slash-separated ``<owner>/<repo>`` for GitHub remotes, or the
       legacy slugified ``<host>_<owner>_<repo>`` key for other remotes.
    3. Slugified basename plus a short hash of the absolute primary
       path, so duplicate basenames stay distinct.
    """
    if explicit:
        explicit = explicit.strip()
    if explicit:
        return _sanitize_project_key(explicit)

    urls = _list_git_remote_urls(primary_workspace_dir)
    if len(urls) == 1:
        normalized = _normalize_git_url(urls[0])
        if normalized:
            host, sep, path = normalized.partition("/")
            if sep and host.lower() == "github.com":
                return _sanitize_project_key(path)
            return _sanitize_project_key(normalized.replace("/", "_"))

    return _project_key_from_path(primary_workspace_dir)


def _default_state_root() -> str:
    """Return the platform-specific workspaces state root directory.

    - If ``$XDG_STATE_HOME`` is set: ``$XDG_STATE_HOME/sase/workspaces``.
    - macOS without ``$XDG_STATE_HOME``:
      ``~/Library/Application Support/sase/workspaces``.
    - Linux/other POSIX without ``$XDG_STATE_HOME``:
      ``~/.local/state/sase/workspaces``.
    - Windows: ``%LOCALAPPDATA%\\sase\\workspaces``.
    """
    xdg = os.environ.get("XDG_STATE_HOME")
    if xdg:
        return str(Path(xdg) / "sase" / "workspaces")

    if sys.platform == "darwin":
        return str(
            Path.home() / "Library" / "Application Support" / "sase" / "workspaces"
        )
    if sys.platform == "win32":
        local = os.environ.get("LOCALAPPDATA")
        if local:
            return str(Path(local) / "sase" / "workspaces")
        return str(Path.home() / "AppData" / "Local" / "sase" / "workspaces")

    return str(Path.home() / ".local" / "state" / "sase" / "workspaces")


def managed_workspace_root(*, env: Mapping[str, str] | None = None) -> str:
    """Return the base directory containing managed workspace checkouts.

    ``SASE_WORKSPACE_ROOT`` takes precedence over the platform state-directory
    default, matching :func:`_resolve_root`.  The returned path is the shared
    base root; project keys are appended by :class:`WorkspaceStore`.
    """
    source = os.environ if env is None else env
    override = source.get(WORKSPACE_ROOT_ENV, "").strip()
    return override or _default_state_root()


@dataclass(frozen=True)
class _ResolvedRoot:
    policy: RootPolicy
    root_dir: str


def _resolve_root(
    primary_workspace_dir: str,
    *,
    config_root: object,
    project_key: str,
    env: Mapping[str, str],
) -> _ResolvedRoot:
    """Pick the managed workspaces root, honoring ``SASE_WORKSPACE_ROOT``."""
    override = env.get(WORKSPACE_ROOT_ENV, "").strip()
    if override:
        return _ResolvedRoot(
            policy="absolute",
            root_dir=str(Path(override) / project_key),
        )

    raw_value = DEFAULT_WORKSPACE_ROOT if config_root is None else str(config_root)
    value = raw_value.strip() or DEFAULT_WORKSPACE_ROOT
    if value == "adjacent":
        abs_primary = os.path.abspath(primary_workspace_dir.rstrip("/"))
        parent = os.path.dirname(abs_primary) or os.sep
        return _ResolvedRoot(policy="adjacent", root_dir=parent)

    if value == "xdg-state":
        return _ResolvedRoot(
            policy="xdg-state",
            root_dir=str(Path(_default_state_root()) / project_key),
        )

    if os.path.isabs(value):
        return _ResolvedRoot(
            policy="absolute",
            root_dir=str(Path(value) / project_key),
        )

    raise ValueError(
        f"Unsupported workspace.root value: {value!r} "
        "(expected 'adjacent', 'xdg-state', or an absolute path)"
    )


def _coerce_workspace_section(config: Mapping[str, Any] | None) -> dict[str, Any]:
    """Return the ``workspace:`` config section as a dict."""
    if not config:
        return {}
    section = config.get("workspace", {}) if isinstance(config, Mapping) else {}
    if not isinstance(section, Mapping):
        return {}
    return dict(section)


class WorkspaceStore:
    """Resolve workspace paths for one primary project checkout.

    The store is keyed on a primary workspace directory.  Resolution
    follows the configured ``workspace.root`` policy with
    ``SASE_WORKSPACE_ROOT`` taking precedence.  Resolution is pure: no
    directories are created.
    """

    def __init__(
        self,
        primary_workspace_dir: str,
        *,
        config: Mapping[str, Any] | None = None,
        env: Mapping[str, str] | None = None,
    ) -> None:
        if not primary_workspace_dir:
            raise ValueError("primary_workspace_dir is required")

        section = _coerce_workspace_section(config)
        self._primary_workspace_dir = primary_workspace_dir
        self._env: Mapping[str, str] = env if env is not None else os.environ
        self._cleanup_ttl_days = _positive_int(section.get("cleanup_ttl_days"), 14)

        explicit_key = section.get("project_key", "") or ""
        explicit_key = explicit_key.strip() if isinstance(explicit_key, str) else ""
        self._project_key = _derive_project_key(
            primary_workspace_dir, explicit=explicit_key or None
        )
        self._root = _resolve_root(
            primary_workspace_dir,
            config_root=section.get("root"),
            project_key=self._project_key,
            env=self._env,
        )
        abs_primary = os.path.abspath(primary_workspace_dir.rstrip("/"))
        self._project_basename = os.path.basename(abs_primary) or "workspace"

    @property
    def primary_workspace_dir(self) -> str:
        return self._primary_workspace_dir

    @property
    def project_key(self) -> str:
        return self._project_key

    @property
    def root_policy(self) -> RootPolicy:
        return self._root.policy

    @property
    def root_dir(self) -> str:
        return self._root.root_dir

    @property
    def cleanup_ttl_days(self) -> int:
        return self._cleanup_ttl_days

    def resolve(self, workspace_num: int) -> WorkspacePath:
        """Return the resolved ``WorkspacePath`` for *workspace_num*.

        ``workspace_num == 0`` is the primary checkout in every policy.
        Under ``adjacent``, the legacy ``workspace_num == 1`` also maps
        to the primary checkout so that existing ``_get_git_clone_dir``
        call sites keep their behavior.
        """
        if workspace_num < 0:
            raise ValueError(f"workspace_num must be >= 0, got {workspace_num}")

        is_primary = workspace_num == PRIMARY_WORKSPACE_NUM or (
            self._root.policy == "adjacent"
            and workspace_num == LEGACY_PRIMARY_WORKSPACE_NUM
        )

        if is_primary:
            return WorkspacePath(
                project_key=self._project_key,
                workspace_num=workspace_num,
                root_dir=self._root.root_dir,
                checkout_dir=self._primary_workspace_dir,
                materialization="primary",
                generation=0,
                display_label=self._project_basename,
            )

        if self._root.policy == "adjacent":
            base = self._primary_workspace_dir.rstrip("/")
            return WorkspacePath(
                project_key=self._project_key,
                workspace_num=workspace_num,
                root_dir=self._root.root_dir,
                checkout_dir=f"{base}_{workspace_num}/",
                materialization="git-clone",
                generation=0,
                display_label=f"{self._project_basename}_{workspace_num}",
            )

        # ``xdg-state`` and absolute roots place each managed workspace
        # under ``<root>/<project_basename>_<num>/``.  The trailing slash
        # mirrors the adjacent convention so downstream string handling
        # stays consistent.
        checkout_path = (
            Path(self._root.root_dir) / f"{self._project_basename}_{workspace_num}"
        )
        return WorkspacePath(
            project_key=self._project_key,
            workspace_num=workspace_num,
            root_dir=self._root.root_dir,
            checkout_dir=f"{checkout_path}/",
            materialization="git-clone",
            generation=0,
            display_label=f"{self._project_basename}_{workspace_num}",
        )


def _positive_int(value: Any, default: int) -> int:
    """Coerce *value* to a non-negative int, falling back to *default*."""
    try:
        result = int(value)
    except (TypeError, ValueError):
        return default
    return result if result >= 0 else default


__all__ = [
    "LEGACY_PRIMARY_WORKSPACE_NUM",
    "PRIMARY_WORKSPACE_NUM",
    "DEFAULT_WORKSPACE_ROOT",
    "WORKSPACE_ROOT_ENV",
    "WorkspacePath",
    "WorkspaceStore",
    "managed_workspace_root",
]
