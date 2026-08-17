"""CLI handler for ``sase glossary show``."""

from __future__ import annotations

import argparse
import sys
from typing import cast

from rich.console import Console

from sase.glossary.cli_common import GlossaryCliError, resolve_glossary_cli_project
from sase.glossary.render import GlossaryShowFormat, render_glossary_closure
from sase.glossary.resolution import GlossaryLookupError, resolve_glossary_closure


def handle_glossary_show_command(
    args: argparse.Namespace, *, console: Console | None = None
) -> None:
    """Print one or more glossary terms and their reference closure."""
    try:
        resolved = resolve_glossary_cli_project(getattr(args, "project", None))
    except GlossaryCliError as exc:
        print(f"sase glossary show: {exc}", file=sys.stderr)
        sys.exit(1)

    depth = getattr(args, "depth", None)
    output_format = cast(GlossaryShowFormat, getattr(args, "format", "rich"))
    terms: list[str] = args.term

    try:
        closure = resolve_glossary_closure(
            resolved.catalog, resolved.compiled, terms, depth=depth
        )
    except GlossaryLookupError as exc:
        print(f"sase glossary show: {exc}", file=sys.stderr)
        sys.exit(1)

    render_glossary_closure(
        closure,
        project_name=resolved.project_name,
        output_format=output_format,
        console=console,
    )


__all__ = ["handle_glossary_show_command"]
