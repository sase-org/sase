"""CLI handler for ``sase snippet show``."""

from __future__ import annotations

import argparse
import sys
from typing import cast

from rich.console import Console

from sase.snippet.cli_common import (
    SnippetCliError,
    SnippetShowFormat,
    catalog_project_name,
    exit_snippet_error,
    load_snippet_cli_catalog,
    snippet_entry_json,
    write_json,
)
from sase.snippet.cli_render import print_rich, show_markdown, show_renderable
from sase.snippet.lookup import SnippetLookupError, lookup_snippet


def handle_snippet_show_command(
    args: argparse.Namespace, *, console: Console | None = None
) -> None:
    """Print one snippet's raw/composed definition, sources, and relations."""
    reference = args.trigger
    try:
        catalog = load_snippet_cli_catalog(getattr(args, "project", None))
        entry = lookup_snippet(catalog, reference)
    except (SnippetCliError, SnippetLookupError) as exc:
        exit_snippet_error("show", exc)

    project_name = catalog_project_name(catalog)
    output_format = cast(SnippetShowFormat, getattr(args, "format", "rich"))
    if output_format == "json":
        write_json(
            {
                "project": project_name,
                "reference": reference,
                "snippet": snippet_entry_json(entry),
            }
        )
        return
    if output_format == "markdown":
        sys.stdout.write(show_markdown(entry, project_name=project_name))
        return
    target = console or Console()
    print_rich(target, show_renderable(entry, project_name=project_name))


__all__ = ["handle_snippet_show_command"]
