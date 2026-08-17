"""CLI handler for ``sase glossary read``."""

from __future__ import annotations

import argparse
import sys

from rich.console import Console

from sase.agent.identity import AgentIdentityError
from sase.glossary.cli_common import GlossaryCliError
from sase.glossary.cli_show import emit_glossary_view, resolve_glossary_view
from sase.glossary.read_log import (
    GlossaryReadError,
    append_glossary_read_event,
    build_glossary_read_event,
    normalize_read_reason,
    require_agent_identity,
)
from sase.glossary.resolution import GlossaryClosure, GlossaryLookupError


def handle_glossary_read_command(
    args: argparse.Namespace, *, console: Console | None = None
) -> None:
    """Print a glossary closure and append one audited read event first."""
    try:
        reason = normalize_read_reason(args.reason)
        agent = require_agent_identity()
        resolved, closure = resolve_glossary_view(args)
        terms, related_terms, definition_bytes = _closure_audit_fields(closure)
        event = build_glossary_read_event(
            reason=reason,
            agent=agent,
            terms=terms,
            related_terms=related_terms,
            depth_limit=getattr(args, "depth", None),
            definition_bytes=definition_bytes,
            source_path=resolved.config_path,
            project=resolved.project_name,
        )
        append_glossary_read_event(event)
    except (
        AgentIdentityError,
        GlossaryCliError,
        GlossaryLookupError,
        GlossaryReadError,
        OSError,
    ) as exc:
        print(f"sase glossary read: {exc}", file=sys.stderr)
        sys.exit(1)

    emit_glossary_view(resolved, closure, args, console=console)


def _closure_audit_fields(
    closure: GlossaryClosure,
) -> tuple[tuple[str, ...], tuple[str, ...], int]:
    terms = tuple(
        node.entry.term for node in closure.nodes if node.origin == "requested"
    )
    related_terms = tuple(
        node.entry.term for node in closure.nodes if node.origin == "related"
    )
    definition_bytes = sum(
        len(node.entry.definition.strip().encode("utf-8")) for node in closure.nodes
    )
    return terms, related_terms, definition_bytes


__all__ = ["handle_glossary_read_command"]
