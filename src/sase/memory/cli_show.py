"""CLI handler for ``sase memory show``."""

from __future__ import annotations

import argparse
from pathlib import Path
import sys
from typing import Literal, cast

from rich.console import Console

from sase.memory.read_log import MemoryReadError
from sase.memory.render import MemoryShowFormat
from sase.memory.selector import (
    ResolvedMemorySelectorBatch,
    resolve_memory_selector_batch,
)
from sase.memory.selector_render import render_memory_selector_batch


def resolve_memory_view(args: argparse.Namespace) -> ResolvedMemorySelectorBatch:
    """Resolve the selector batch shared by ``show`` and ``read``.

    A bare web selector naming a web whose roster loads on demand is refused
    here with an ``on_demand_web`` error unless ``-a/--all-strands`` was
    passed. ``read`` argument namespaces carry ``reason``; ``show`` ones do
    not, which selects the guard's hint wording.
    """
    home_root = Path.home()
    if bool(getattr(args, "all_strands", False)):
        return resolve_memory_selector_batch(
            list(args.selectors),
            depth=getattr(args, "depth", None),
            project_ref=getattr(args, "project", None),
            home_root=home_root,
        )
    command: Literal["read", "show"] = "read" if hasattr(args, "reason") else "show"
    return resolve_memory_selector_batch(
        list(args.selectors),
        depth=getattr(args, "depth", None),
        project_ref=getattr(args, "project", None),
        home_root=home_root,
        refuse_on_demand_bare_webs=command,
    )


def emit_memory_view(
    view: ResolvedMemorySelectorBatch,
    args: argparse.Namespace,
    *,
    console: Console | None = None,
) -> None:
    """Print a resolved selector batch using the same renderer as ``show``."""
    output_format = cast(MemoryShowFormat, getattr(args, "format", "markdown"))
    render_memory_selector_batch(view, output_format=output_format, console=console)


def handle_memory_show_command(
    args: argparse.Namespace, *, console: Console | None = None
) -> None:
    """Print one or more reference memory selectors without an audited read."""
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
