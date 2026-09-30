"""Helpers shared by the create/update/delete bead CLI command handlers."""

from __future__ import annotations

from sase.agent.identity import discover_agent_identity
from sase.bead.project import BeadProject


def mutation_outcome_ids(outcome: dict[str, object], field: str) -> list[str]:
    """Read one list of bead ids out of a store mutation outcome."""
    values = outcome.get(field)
    if not isinstance(values, list):
        return []
    return [str(value) for value in values]


def resolve_mutation_author(project: BeadProject) -> str:
    """Attribute a mutation to the acting agent, or to the store owner."""
    identity = discover_agent_identity()
    return identity.name if identity is not None else project.owner


def print_attachment_echo_rows(rows: list[str]) -> None:
    """Print attachment write-echo rows to stderr.

    Rows are rich-rendered on an interactive terminal (``hint:`` rows dim)
    and plain otherwise (stderr is not a TTY or ``SASE_AGENT`` is set).
    """
    if not rows:
        return
    import os
    import sys

    if sys.stderr.isatty() and not os.environ.get("SASE_AGENT"):
        from rich.console import Console
        from rich.markup import escape

        console = Console(stderr=True)
        for row in rows:
            if row.startswith("hint: "):
                console.print(escape(row), style="dim")
            else:
                console.print(escape(row))
    else:
        for row in rows:
            print(row, file=sys.stderr)
