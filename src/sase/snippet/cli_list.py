"""CLI handler for ``sase snippet list``."""

from __future__ import annotations

import argparse
import sys
from typing import cast

from rich.console import Console

from sase.snippet.cli_common import (
    SnippetCliError,
    SnippetListFormat,
    catalog_project_name,
    exit_snippet_error,
    load_snippet_cli_catalog,
    snippet_entry_json,
    snippet_layer_diagnostic_json,
    write_json,
)
from sase.snippet.cli_render import build_list_table, print_rich
from sase.snippet.text_filter import filter_snippet_entries


def handle_snippet_list_command(
    args: argparse.Namespace, *, console: Console | None = None
) -> None:
    """List effective snippets for a project, filtered and formatted per *args*."""
    try:
        catalog = load_snippet_cli_catalog(getattr(args, "project", None))
    except SnippetCliError as exc:
        exit_snippet_error("list", exc)

    pattern = getattr(args, "pattern", None)
    include_definitions = bool(getattr(args, "definitions", False))
    output_format = cast(SnippetListFormat, getattr(args, "format", "table"))
    entries = filter_snippet_entries(
        catalog.entries,
        pattern=pattern,
        include_definitions=include_definitions,
    )
    project_name = catalog_project_name(catalog)

    if output_format == "json":
        write_json(
            {
                "definitions": include_definitions,
                "diagnostics": [
                    snippet_layer_diagnostic_json(item)
                    for item in catalog.layer_diagnostics
                ],
                "pattern": pattern,
                "project": project_name,
                "snippets": [snippet_entry_json(entry) for entry in entries],
            }
        )
        return

    if output_format == "names":
        for entry in entries:
            print(entry.trigger)
        if not entries:
            print(_no_match_message(pattern), file=sys.stderr)
        return

    if not entries:
        print(_no_match_message(pattern))
        return

    target = console or Console()
    print_rich(
        target,
        build_list_table(
            project_name=project_name,
            entries=entries,
            diagnostics=catalog.layer_diagnostics,
        ),
    )


def _no_match_message(pattern: str | None) -> str:
    if pattern:
        return f"no snippets matched: {pattern}"
    return "no snippets configured"


__all__ = ["handle_snippet_list_command"]
