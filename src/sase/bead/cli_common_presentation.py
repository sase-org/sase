"""Single-line row presentation for bead CLI handlers."""

from __future__ import annotations

from sase.bead.model import Issue, Status


def status_icon(status: Status) -> str:
    from sase.bead_status_presentation import bead_status_presentation

    return bead_status_presentation(status).glyph


def created_cell(issue: Issue, *, use_color: bool) -> str:
    """Return the trailing ``⧖ <age>`` fragment for a single-line bead row.

    Every compact CLI row surface (list, search, dependency list and tree)
    appends this so the bead's own creation time reads identically across all
    of them, and stays distinct from the dependency edge's ``added <ts> by
    <who>`` provenance line. Empty when the bead carries no usable timestamp,
    so the row simply ends where it used to instead of trailing whitespace.
    """
    from sase.bead_time_presentation import bead_created_cli

    cell = bead_created_cli(issue.created_at, use_color=use_color)
    return f"  {cell}" if cell else ""
