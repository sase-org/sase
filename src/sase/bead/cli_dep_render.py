"""Shared terminal rendering helpers for dependency commands."""

from __future__ import annotations

import os
import sys

from sase.bead.model import Issue, Status
from sase.bead_status_presentation import bead_status_presentation

ANSI_RESET = "\x1b[0m"
ANSI_BOLD_BLUE = "\x1b[1;34m"
ANSI_YELLOW = "\x1b[33m"
ACTIVE_STATUSES = frozenset({Status.OPEN, Status.CLAIMED, Status.IN_PROGRESS})


def render_issue(issue: Issue, *, label: bool, use_color: bool) -> str:
    """Render a dependency graph issue row."""
    presentation = bead_status_presentation(issue.status)
    glyph = styled(presentation.glyph, presentation.cli_style, use_color)
    issue_id = styled(issue.id, ANSI_BOLD_BLUE, use_color)
    suffix = f"   [{presentation.label}]" if label else ""
    return f"{glyph} {issue_id} · {issue.title}{suffix}"


def resolve_color(color: str) -> bool:
    """Resolve a CLI color mode against the current process environment."""
    if color == "always":
        return True
    if color == "never":
        return False
    if os.environ.get("NO_COLOR") is not None:
        return False
    return sys.stdout.isatty()


def styled(value: str, style: str, use_color: bool) -> str:
    """Apply an ANSI style when color output is enabled."""
    if not use_color:
        return value
    return f"{style}{value}{ANSI_RESET}"
