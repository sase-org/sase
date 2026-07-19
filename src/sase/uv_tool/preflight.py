"""Local-path safety checks for reconstructed ``uv tool`` requirements."""

from __future__ import annotations

import os
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import unquote, urlsplit

from sase.linked_repos import (
    EXTERNAL_REPO_CLONES_SUBDIR,
    LINKED_REPO_CLONES_SUBDIR,
)
from sase.uv_tool.errors import UvToolError
from sase.uv_tool.receipt import ReconstructedRequirements, Requirement
from sase.workspace_provider.store import managed_workspace_root


@dataclass(frozen=True)
class _MissingLocalRequirement:
    """A reconstructed plugin requirement whose local source disappeared."""

    requirement: Requirement
    path: Path


def _requirement_local_path(requirement: Requirement) -> Path | None:
    """Return the normalized local source path for *requirement*, if any.

    Editable sources are always local. Direct ``file:`` URLs and scheme-less
    ``url`` / receipt ``directory`` values are local too; index, git, and HTTP
    sources are intentionally ignored.
    """
    raw = requirement.editable
    if raw is None:
        raw = _local_url_path(requirement.url)
    if raw is None:
        return None
    return _normalized_path(raw)


def _is_ephemeral_plugin_path(path: str | Path) -> bool:
    """Whether *path* lives in a managed or workspace-local repo checkout."""
    candidate = _normalized_path(path)
    store_root = _normalized_path(managed_workspace_root())
    if _is_relative_to(candidate, store_root):
        return True
    return any(
        _contains_parts(candidate.parts, subdir)
        for subdir in (EXTERNAL_REPO_CLONES_SUBDIR, LINKED_REPO_CLONES_SUBDIR)
    )


def ephemeral_install_source_error(requirement: Requirement) -> UvToolError | None:
    """Return an actionable error when a new install source is ephemeral."""
    path = _requirement_local_path(requirement)
    if path is None or not _is_ephemeral_plugin_path(path):
        return None
    name = requirement.name
    return UvToolError(
        f"plugin '{name}' cannot be installed from {path}: workspace-local "
        "checkouts are ephemeral. Install from a durable source with "
        f"`sase plugin install --git {name}` or use a durable checkout path "
        "outside the managed workspace store."
    )


def _missing_local_requirements(
    requirements: ReconstructedRequirements | Iterable[Requirement],
) -> tuple[_MissingLocalRequirement, ...]:
    """Return reconstructed plugin requirements whose local paths are missing.

    A :class:`ReconstructedRequirements` input checks its injected plugins. The
    primary ``sase`` requirement is deliberately excluded because the recovery
    command in this plugin-focused preflight is ``sase plugin uninstall``.
    Callers may pass an explicit iterable when they need a different scope.
    """
    if isinstance(requirements, ReconstructedRequirements):
        candidates = requirements.plugins
    else:
        candidates = tuple(requirements)

    missing: list[_MissingLocalRequirement] = []
    for requirement in candidates:
        path = _requirement_local_path(requirement)
        if path is None:
            continue
        try:
            exists = path.exists()
        except (OSError, ValueError):
            # Odd receipt values must not crash update/version rendering. Let uv
            # retain responsibility for sources that cannot be probed safely.
            continue
        if not exists:
            missing.append(_MissingLocalRequirement(requirement, path))
    return tuple(missing)


def missing_local_requirements_error(
    requirements: ReconstructedRequirements | Iterable[Requirement],
) -> UvToolError | None:
    """Return the shared actionable error for the first missing local source."""
    missing = _missing_local_requirements(requirements)
    if not missing:
        return None
    entry = missing[0]
    name = entry.requirement.name
    return UvToolError(
        f"plugin '{name}' has a local install source that no longer exists: "
        f"{entry.path}. Run `sase plugin uninstall {name}`, then reinstall from "
        "a durable source (for example, "
        f"`sase plugin install --git {name}`)."
    )


def _local_url_path(value: str | None) -> str | None:
    if value is None:
        return None
    parsed = urlsplit(value)
    if parsed.scheme == "file":
        if parsed.netloc and parsed.netloc != "localhost":
            return f"//{parsed.netloc}{unquote(parsed.path)}"
        return unquote(parsed.path)
    if parsed.scheme or "://" in value:
        return None
    return value


def _normalized_path(path: str | Path) -> Path:
    return Path(os.path.abspath(os.path.expanduser(os.fspath(path))))


def _is_relative_to(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
    except ValueError:
        return False
    return True


def _contains_parts(parts: tuple[str, ...], needle: tuple[str, ...]) -> bool:
    width = len(needle)
    return any(parts[index : index + width] == needle for index in range(len(parts)))


__all__ = [
    "ephemeral_install_source_error",
    "missing_local_requirements_error",
]
