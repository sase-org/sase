"""CLI handler for ``sase glossary all``."""

from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence
from typing import cast

from rich.console import Console

from sase.core.glossary_facade import GlossaryEntry
from sase.glossary.cli_common import GlossaryCliError, resolve_glossary_cli_project
from sase.glossary.render import GlossaryShowFormat, render_glossary_catalog
from sase.glossary.resolution import resolve_glossary_closure


def handle_glossary_all_command(
    args: argparse.Namespace, *, console: Console | None = None
) -> None:
    """Print every glossary term configured for a project."""
    try:
        resolved = resolve_glossary_cli_project(getattr(args, "project", None))
    except GlossaryCliError as exc:
        print(f"sase glossary all: {exc}", file=sys.stderr)
        sys.exit(1)

    closure = resolve_glossary_closure(
        resolved.catalog,
        resolved.compiled,
        _catalog_order(resolved.catalog.entries),
    )
    render_glossary_catalog(
        closure,
        project_name=resolved.project_name,
        output_format=cast(GlossaryShowFormat, getattr(args, "format", "rich")),
        console=console,
    )


def _catalog_order(entries: Sequence[GlossaryEntry]) -> tuple[GlossaryEntry, ...]:
    return tuple(
        sorted(entries, key=lambda entry: (entry.normalized_term, entry.index))
    )


__all__ = ["handle_glossary_all_command"]
