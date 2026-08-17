"""CLI handler for ``sase glossary show``."""

from __future__ import annotations

import argparse
import sys
from typing import cast

from rich.console import Console

from sase.glossary.cli_common import (
    GlossaryCliError,
    ResolvedGlossaryProject,
    resolve_glossary_cli_project,
)
from sase.glossary.render import GlossaryShowFormat, render_glossary_closure
from sase.glossary.resolution import (
    GlossaryClosure,
    GlossaryLookupError,
    resolve_glossary_closure,
)


def resolve_glossary_view(
    args: argparse.Namespace,
) -> tuple[ResolvedGlossaryProject, GlossaryClosure]:
    """Resolve the project and term closure shared by ``show`` and ``read``."""
    resolved = resolve_glossary_cli_project(getattr(args, "project", None))
    closure = resolve_glossary_closure(
        resolved.catalog,
        resolved.compiled,
        args.term,
        depth=getattr(args, "depth", None),
    )
    return resolved, closure


def emit_glossary_view(
    resolved: ResolvedGlossaryProject,
    closure: GlossaryClosure,
    args: argparse.Namespace,
    *,
    console: Console | None = None,
) -> None:
    """Print a resolved closure using the same renderer as ``show``."""
    output_format = cast(GlossaryShowFormat, getattr(args, "format", "rich"))
    render_glossary_closure(
        closure,
        project_name=resolved.project_name,
        output_format=output_format,
        console=console,
    )


def handle_glossary_show_command(
    args: argparse.Namespace, *, console: Console | None = None
) -> None:
    """Print one or more glossary terms and their reference closure."""
    try:
        resolved, closure = resolve_glossary_view(args)
    except (GlossaryCliError, GlossaryLookupError) as exc:
        print(f"sase glossary show: {exc}", file=sys.stderr)
        sys.exit(1)

    emit_glossary_view(resolved, closure, args, console=console)


__all__ = [
    "emit_glossary_view",
    "handle_glossary_show_command",
    "resolve_glossary_view",
]
