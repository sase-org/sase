"""CLI handler for ``sase snippet delete``."""

from __future__ import annotations

import argparse
from typing import cast

from rich.console import Console

from sase.snippet.cli_common import (
    SnippetWriteFormat,
    exit_snippet_error,
    snippet_write_json,
    write_error_types,
    write_json,
)
from sase.snippet.cli_render import build_write_table, print_rich
from sase.snippet.mutation import delete_snippet


def handle_snippet_delete_command(
    args: argparse.Namespace, *, console: Console | None = None
) -> None:
    """Delete a writable snippet (or preview the delete) and print the outcome."""
    project_ref = getattr(args, "project", None)
    dry_run = bool(getattr(args, "dry_run", False))
    try:
        outcome = delete_snippet(
            project_ref,
            args.trigger,
            all_layers=bool(getattr(args, "all_layers", False)),
            dry_run=dry_run,
        )
    except write_error_types() as exc:
        exit_snippet_error("delete", exc)

    output_format = cast(SnippetWriteFormat, getattr(args, "format", "rich"))
    if output_format == "json":
        write_json(snippet_write_json(outcome))
        return
    target = console or Console()
    print_rich(target, build_write_table(outcome))


__all__ = ["handle_snippet_delete_command"]
