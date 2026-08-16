"""Subprocess display helpers for ACE proc rendering."""

from __future__ import annotations

import shlex
from collections.abc import Sequence


def command_display(argv: Sequence[object]) -> str:
    """Return a shell-like command string for display only."""
    return shlex.join(str(part) for part in argv)
