"""CLI handler for ``sase memory read``."""

from __future__ import annotations

import argparse
from pathlib import Path
import sys

from sase.memory.read_log import (
    AgentIdentityError,
    MemoryReadError,
    MemoryReadContent,
    append_memory_read_event,
    build_memory_read_event,
    normalize_read_reason,
    read_memory_content,
    require_agent_identity,
    validate_memory_read_path,
)
from sase.memory.notes import discover_memory_notes, render_children_section


def handle_memory_read_command(args: argparse.Namespace) -> None:
    """Read an allowed memory file and append an audit event."""
    try:
        reason = normalize_read_reason(args.reason)
        agent = require_agent_identity()
        validated_path = validate_memory_read_path(
            args.memory_path,
            home_root=Path.home(),
        )
        content = read_memory_content(validated_path)
        output = _render_memory_read_output(content)
        event = build_memory_read_event(
            content,
            reason=reason,
            agent=agent,
            cwd=Path.cwd(),
        )
        append_memory_read_event(event)
    except (AgentIdentityError, MemoryReadError, OSError, UnicodeError) as exc:
        print(f"sase memory read: {exc}", file=sys.stderr)
        sys.exit(1)

    sys.stdout.write(output)


def _render_memory_read_output(content: MemoryReadContent) -> str:
    notes = discover_memory_notes(content.path.content_root)
    children_section = render_children_section(notes, content.path.note)
    if not children_section:
        return content.body

    body = content.body
    if body and not body.endswith("\n"):
        body += "\n"
    if body and not body.endswith("\n\n"):
        body += "\n"
    return body + children_section
