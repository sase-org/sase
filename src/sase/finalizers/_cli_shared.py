"""Shared helpers for the ``sase final`` CLI split modules."""

from __future__ import annotations

from rich.console import Console


def print_error(console: Console | None, message: str) -> None:
    """Print an error message to *console* (stderr by default)."""

    output = console or Console(stderr=True)
    output.print(f"[red]{message}[/red]")


__all__ = [
    "print_error",
]
