"""CLI handler for ``sase memory read``."""

from __future__ import annotations

import argparse
from pathlib import Path
import sys

from rich.console import Console

from sase.agent.identity import AgentIdentity
from sase.memory.cli_show import emit_memory_view, resolve_memory_view
from sase.memory.read_log import (
    AgentIdentityError,
    MemoryReadError,
    MemoryReadEvent,
    append_memory_read_event,
    build_memory_read_batch_event,
    build_memory_read_event,
    normalize_read_reason,
    require_agent_identity,
)
from sase.memory.selector import ResolvedMemorySelectorBatch


def handle_memory_read_command(
    args: argparse.Namespace, *, console: Console | None = None
) -> None:
    """Resolve a memory selector batch and append one audit event first."""
    try:
        reason = normalize_read_reason(args.reason)
        agent = require_agent_identity()
        view = resolve_memory_view(args)
        event = _build_read_event(view, reason=reason, agent=agent)
        append_memory_read_event(event)
    except (AgentIdentityError, MemoryReadError, OSError, UnicodeError) as exc:
        print(f"sase memory read: {exc}", file=sys.stderr)
        sys.exit(1)

    emit_memory_view(view, args, console=console)


def _build_read_event(
    view: ResolvedMemorySelectorBatch, *, reason: str, agent: AgentIdentity
) -> MemoryReadEvent:
    if view.is_single_note:
        return build_memory_read_event(
            view.notes[0].content,
            reason=reason,
            agent=agent,
            cwd=Path.cwd(),
        )

    resolved_targets, included_targets, scope_origin = _batch_targets(view)
    byte_count = sum(note.content.byte_count for note in view.notes) + sum(
        len(node.strand.body.encode("utf-8"))
        for section in view.web_sections
        for node in section.nodes
    )
    frontmatter_stripped = any(note.content.frontmatter_stripped for note in view.notes)
    return build_memory_read_batch_event(
        kind=view.kind,
        selectors=view.selectors,
        resolved_targets=resolved_targets,
        included_targets=included_targets,
        depth=view.depth,
        scope_origin=scope_origin,
        byte_count=byte_count,
        frontmatter_stripped=frontmatter_stripped,
        reason=reason,
        agent=agent,
        cwd=Path.cwd(),
    )


def _batch_targets(
    view: ResolvedMemorySelectorBatch,
) -> tuple[tuple[str, ...], tuple[str, ...], tuple[tuple[str, str], ...]]:
    resolved: list[str] = [note.content.path.canonical_path for note in view.notes]
    included: list[str] = []
    scope_origin: list[tuple[str, str]] = []
    for section in view.web_sections:
        for node in section.nodes:
            target = f"{section.web.slug}:{node.strand.slug}"
            if node.origin == "requested":
                resolved.append(target)
            else:
                included.append(target)
            scope_origin.append((target, node.scope))
    return tuple(resolved), tuple(included), tuple(scope_origin)


__all__ = ["handle_memory_read_command"]
