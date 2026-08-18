"""CLI handler for ``sase memory show``."""

from __future__ import annotations

import argparse
from pathlib import Path
import sys
from typing import Literal, cast

from rich.console import Console

from sase.main.init_memory.config import project_memory_name
from sase.memory.notes import discover_memory_notes
from sase.memory.read_log import (
    MemoryReadError,
    read_memory_content,
    validate_memory_read_path,
)
from sase.memory.render import MemoryShowFormat, ResolvedMemoryNote, render_memory_note


def resolve_memory_view(args: argparse.Namespace) -> ResolvedMemoryNote:
    """Resolve the note, children, and origin shared by ``show`` and ``read``."""
    home_root = Path.home()
    validated_path = validate_memory_read_path(args.memory_path, home_root=home_root)
    content = read_memory_content(validated_path)
    children = discover_memory_notes(content.path.content_root)

    resolved_home_root = home_root.expanduser().resolve(strict=False)
    origin: Literal["home", "project"] = (
        "home" if content.path.content_root == resolved_home_root else "project"
    )
    return ResolvedMemoryNote(
        content=content,
        children=children,
        origin=origin,
        project_name=project_memory_name(Path.cwd()),
    )


def emit_memory_view(
    view: ResolvedMemoryNote,
    args: argparse.Namespace,
    *,
    console: Console | None = None,
) -> None:
    """Print a resolved note using the same renderer as ``show``."""
    output_format = cast(MemoryShowFormat, getattr(args, "format", "markdown"))
    render_memory_note(view, output_format=output_format, console=console)


def handle_memory_show_command(
    args: argparse.Namespace, *, console: Console | None = None
) -> None:
    """Print one long-term memory note without recording an audited read."""
    try:
        view = resolve_memory_view(args)
    except (MemoryReadError, OSError, UnicodeError) as exc:
        print(f"sase memory show: {exc}", file=sys.stderr)
        sys.exit(1)

    emit_memory_view(view, args, console=console)


__all__ = [
    "emit_memory_view",
    "handle_memory_show_command",
    "resolve_memory_view",
]
