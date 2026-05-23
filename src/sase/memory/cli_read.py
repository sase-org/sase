"""CLI handler for ``sase memory read``."""

from __future__ import annotations

import argparse
from pathlib import Path
import sys

from sase.memory.read_log import (
    MemoryReadError,
    append_memory_read_event,
    build_memory_read_event,
    normalize_read_reason,
    read_memory_content,
    require_agent_identity,
    validate_memory_read_path,
)


def handle_memory_read_command(args: argparse.Namespace) -> None:
    """Read an allowed memory file and append an audit event."""
    try:
        reason = normalize_read_reason(args.reason)
        agent = require_agent_identity()
        validated_path = validate_memory_read_path(args.memory_path)
        content = read_memory_content(validated_path)
        event = build_memory_read_event(
            content,
            reason=reason,
            agent=agent,
            cwd=Path.cwd(),
        )
        append_memory_read_event(event)
    except (MemoryReadError, OSError, UnicodeError) as exc:
        print(f"sase memory read: {exc}", file=sys.stderr)
        sys.exit(1)

    sys.stdout.write(content.body)
