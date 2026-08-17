"""CLI handler for ``sase glossary del``."""

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
from sase.glossary.mutation import delete_glossary_term


def handle_glossary_del_command(
    args: argparse.Namespace, *, console: Console | None = None
) -> None:
    """Delete a glossary term (or preview the delete) and print the outcome."""
    project_ref = getattr(args, "project", None)
    dry_run = bool(getattr(args, "dry_run", False))
    try:
        outcome = delete_glossary_term(
            project_ref,
            args.term,
            dry_run=dry_run,
        )
    except write_error_types() as exc:
        exit_glossary_write_error("del", exc, project_ref=project_ref)

    emit_glossary_write_outcome(
        outcome,
        operation="del",
        output_format=cast(GlossaryWriteFormat, getattr(args, "format", "rich")),
        dry_run=dry_run,
        no_init=bool(getattr(args, "no_init", False)),
        command="del",
        console=console,
    )


__all__ = ["handle_glossary_del_command"]
