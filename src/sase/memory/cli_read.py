"""CLI handler for ``sase memory read``."""

from __future__ import annotations

import argparse
from pathlib import Path
import sys

from rich.console import Console

from sase.memory.cli_show import emit_memory_view, resolve_memory_view
from sase.memory.read_log import (
    AgentIdentityError,
    MemoryReadError,
    append_memory_read_event,
    build_memory_read_event,
    normalize_read_reason,
    require_agent_identity,
)


def handle_memory_read_command(
    args: argparse.Namespace, *, console: Console | None = None
) -> None:
    """Read an allowed memory file and append an audit event."""
    try:
        reason = normalize_read_reason(args.reason)
        agent = require_agent_identity()
        view = resolve_memory_view(args)
        event = build_memory_read_event(
            view.content,
            reason=reason,
            agent=agent,
            cwd=Path.cwd(),
        )
        append_memory_read_event(event)
    except (AgentIdentityError, MemoryReadError, OSError, UnicodeError) as exc:
        print(f"sase memory read: {exc}", file=sys.stderr)
        sys.exit(1)

    emit_memory_view(view, args, console=console)


__all__ = ["handle_memory_read_command"]
