"""Root-level publisher apply scratch left by an interrupted v2 payload write."""

from __future__ import annotations

import logging
from pathlib import Path
import shutil

_logger = logging.getLogger(__name__)

_PUBLICATION_SCRATCH_PREFIXES: tuple[str, ...] = (
    ".sase-v2-stage-",
    ".sase-v2-backup-",
)


def _is_publication_scratch_name(name: str) -> bool:
    """Return whether *name* is a root-level publisher stage or backup dir."""

    return name.startswith(_PUBLICATION_SCRATCH_PREFIXES)


def is_publication_scratch_path(path: str) -> bool:
    """Return whether a git-status path sits inside publisher apply scratch."""

    relative = path[2:] if path.startswith("./") else path
    first = relative.split("/", 1)[0]
    return _is_publication_scratch_name(first)


def list_publication_scratch_dirs(repo: Path) -> tuple[Path, ...]:
    """Return root-level ``.sase-v2-stage-*`` / ``.sase-v2-backup-*`` directories."""

    try:
        entries = tuple(
            sorted(
                path
                for path in repo.iterdir()
                if path.is_dir() and _is_publication_scratch_name(path.name)
            )
        )
    except OSError:
        return ()
    return entries


def sweep_publication_scratch(repo: Path) -> str | None:
    """Remove root-level publisher scratch directories and log each removal.

    Tracked payload files are restored from git before this runs, so a backup
    directory is never the only copy of a published file. Returns an error
    string when a directory cannot be removed; successful removals still
    happen for the other directories.
    """

    errors: list[str] = []
    for path in list_publication_scratch_dirs(repo):
        try:
            shutil.rmtree(path)
        except FileNotFoundError:
            continue
        except OSError as exc:
            errors.append(f"{path.name}: {exc}")
            _logger.warning("could not remove publication scratch %s: %s", path, exc)
            continue
        _logger.info("removed stranded publication scratch %s", path)
    if errors:
        return "could not remove publication scratch: " + "; ".join(errors)
    return None


__all__ = [
    "is_publication_scratch_path",
    "list_publication_scratch_dirs",
    "sweep_publication_scratch",
]
