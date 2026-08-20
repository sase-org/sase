"""Small helpers shared by Referenced By refresh implementations."""

from pathlib import Path


def relative_path(root: Path, path: Path) -> str:
    """Render *path* relative to *root* when possible."""

    try:
        return path.relative_to(root).as_posix()
    except ValueError:
        return str(path)
