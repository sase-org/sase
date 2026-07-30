"""Resolve a repository path back to its owning checkout."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class _CheckoutAnchor:
    """Best-effort checkout identity for a path inside a SASE workspace."""

    primary_root: Path
    project_name: str | None


def resolve_checkout_anchor(
    path: str | os.PathLike[str] | None = None,
) -> _CheckoutAnchor:
    """Resolve *path* to its owning checkout root and canonical project name.

    The resolver is intentionally best-effort: it never raises, and when no
    managed-checkout context can be proven it returns the normalized input path
    with no project name.
    """

    start = _normalized_path(path)
    primary_root = _marker_checkout_root(start) or _sase_repos_checkout_root(start)
    if primary_root is None:
        primary_root = start
    return _CheckoutAnchor(
        primary_root=primary_root,
        project_name=_project_name_for_path(start),
    )


def _normalized_path(path: str | os.PathLike[str] | None) -> Path:
    try:
        value = Path(os.getcwd()) if path is None else Path(path)
        return value.expanduser().resolve(strict=False)
    except Exception:
        if path is None:
            return Path(".")
        try:
            return Path(path).expanduser()
        except Exception:
            return Path(str(path))


def _marker_checkout_root(path: Path) -> Path | None:
    try:
        from sase.workspace_provider import find_marker_from_cwd

        found = find_marker_from_cwd(str(path))
    except Exception:
        return None
    if found is None:
        return None
    return _normalized_path(found[0])


def _sase_repos_checkout_root(path: Path) -> Path | None:
    parts = path.parts
    for index in range(len(parts) - 1):
        if parts[index] != "sase" or parts[index + 1] != "repos":
            continue
        if index == 0:
            return Path(path.anchor or os.sep).resolve(strict=False)
        return _normalized_path(Path(*parts[:index]))
    return None


def _project_name_for_path(path: Path) -> str | None:
    try:
        from sase.bead.project_name import infer_project_name_from_cwd

        return infer_project_name_from_cwd(str(path))
    except Exception:
        return None


__all__ = [
    "resolve_checkout_anchor",
]
