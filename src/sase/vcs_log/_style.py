"""Shared Rich styling helpers for ``sase stitch`` commands."""

from __future__ import annotations

import sys
from collections.abc import Iterable
from typing import Any, TextIO

from rich.console import Console


#: House gold accent used for short SHAs (matches the CLI convention).
GOLD = "#D7AF5F"

#: Presence accents for incoming and local-only commits.
INCOMING = "#5FD7FF"
UNPUSHED = "#D7AF5F"

#: Accent for merge-commit markers. Distinct from every REPO_PALETTE entry.
MERGE = "#D787FF"

#: Deterministic per-repo accent palette, cycled in resolved-repo order
#: (primary first, then linked sorted by name, then sidecars).
REPO_PALETTE = (
    "#87D7FF",
    "#5FD75F",
    "#D7AF5F",
    "#AF87FF",
    "#5FD7D7",
    "#D787AF",
)


def make_console(
    color: str, *, file: TextIO | None = None, width: int | None = None
) -> Console:
    """Build a ``rich`` console honoring the ``--color`` mode.

    ``auto`` defers to ``rich`` (color only on a TTY, and never when
    ``NO_COLOR`` is set); ``always`` forces color even under ``NO_COLOR``;
    ``never`` strips it.
    """
    kwargs: dict[str, object] = {"file": file or sys.stdout}
    if width is not None:
        kwargs["width"] = width
    if color == "always":
        kwargs.update(force_terminal=True, no_color=False, color_system="standard")
    elif color == "never":
        kwargs.update(no_color=True)
    return Console(**kwargs)  # type: ignore[arg-type]


def repo_colors(repos: Iterable[Any]) -> dict[str, str]:
    """Assign stable accent colors to repos in resolved order."""
    colors: dict[str, str] = {}
    for i, repo in enumerate(repos):
        name = str(repo.name)
        colors.setdefault(name, REPO_PALETTE[i % len(REPO_PALETTE)])
    return colors


__all__ = [
    "GOLD",
    "INCOMING",
    "MERGE",
    "REPO_PALETTE",
    "UNPUSHED",
    "make_console",
    "repo_colors",
]
