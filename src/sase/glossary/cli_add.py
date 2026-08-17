"""CLI handler for ``sase glossary add``."""

from __future__ import annotations

import argparse
from typing import cast

from rich.console import Console

from sase.glossary.cli_write import (
    GlossaryWriteFormat,
    emit_glossary_write_outcome,
    exit_glossary_write_error,
    write_error_types,
)
from sase.glossary.mutation import add_glossary_term


def handle_glossary_add_command(
    args: argparse.Namespace, *, console: Console | None = None
) -> None:
    """Add a glossary term and print the write outcome."""
    project_ref = getattr(args, "project", None)
    try:
        outcome = add_glossary_term(
            project_ref,
            args.term,
            args.definition,
            aliases=tuple(getattr(args, "alias", None) or ()),
        )
    except write_error_types() as exc:
        exit_glossary_write_error("add", exc, project_ref=project_ref)

    emit_glossary_write_outcome(
        outcome,
        operation="add",
        output_format=cast(GlossaryWriteFormat, getattr(args, "format", "rich")),
        dry_run=False,
        no_init=bool(getattr(args, "no_init", False)),
        command="add",
        console=console,
    )


__all__ = ["handle_glossary_add_command"]
