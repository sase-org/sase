"""Human-facing path rendering for files inside managed SASE workspaces.

Collapses a managed workspace checkout's parent directory into a quiet
``~ws`` root token so pager labels stay short without losing the workspace
or file identity. Display-only: callers that need the exact location keep
using the untouched path.
"""

from __future__ import annotations

import os
from pathlib import Path, PurePath

from sase.content_layout import display_path
from sase.workspace_provider.marker import find_marker_from_cwd
from sase.workspace_provider.store import PRIMARY_WORKSPACE_NUM

WORKSPACE_ROOT_TOKEN = "~ws"


def workspace_display_path(
    path: str | Path,
    *,
    home_root: Path | str | None = None,
) -> str:
    """Render *path* for humans.

    ``~ws/<workspace>/…`` inside a managed workspace checkout, ``~/…``
    under home, otherwise unchanged. Non-path and relative strings pass
    through untouched.
    """
    text = os.fspath(path)
    if not text.startswith("/") and not text.startswith("~"):
        return text

    absolute = os.path.abspath(os.path.expanduser(text))
    try:
        found = find_marker_from_cwd(absolute)
    except (OSError, ValueError):
        found = None

    if found is not None:
        checkout_dir, marker = found
        if marker.workspace_num > PRIMARY_WORKSPACE_NUM:
            try:
                relative = PurePath(absolute).relative_to(checkout_dir)
            except ValueError:
                relative = None
            if relative is not None:
                label = f"{WORKSPACE_ROOT_TOKEN}/{Path(checkout_dir).name}"
                if str(relative) != ".":
                    label = f"{label}/{relative.as_posix()}"
                return label

    return display_path(text, home_root=home_root)


def split_workspace_root(label: str) -> tuple[str, str]:
    """Split a rendered *label* into its muted root token and the rest.

    Returns ``(f"{WORKSPACE_ROOT_TOKEN}/", rest)`` when *label* starts
    with an intact workspace root token, else ``("", label)``.
    """
    prefix = f"{WORKSPACE_ROOT_TOKEN}/"
    if label.startswith(prefix):
        return prefix, label[len(prefix) :]
    return "", label


__all__ = [
    "WORKSPACE_ROOT_TOKEN",
    "split_workspace_root",
    "workspace_display_path",
]
