"""Project-scope detection for initialization commands."""

from __future__ import annotations

from pathlib import Path

from sase.vcs_provider import VCSProviderNotFoundError, detect_vcs_family


def is_project_directory(cwd: Path | str | None = None) -> bool:
    """Return whether *cwd* is inside a version-controlled project."""
    path = Path.cwd() if cwd is None else Path(cwd)
    try:
        return detect_vcs_family(str(path)) is not None
    except VCSProviderNotFoundError:
        # ``detect_vcs_family`` only reaches provider classification after a
        # marker such as .git has already been found. For init scoping, that
        # marker is enough even if the checkout has no classifiable provider.
        return True


__all__ = ["is_project_directory"]
