"""Command orchestration for ``sase xprompt show``."""

from __future__ import annotations

import argparse
import json
import shutil
import sys

from rich.console import Console

from sase.bead.cli_dep_render import resolve_color
from sase.xprompt.cli_show_render import render_show
from sase.xprompt.cli_show_resolve import (
    ShowLookupMiss,
    normalize_show_name,
    resolve_show_record,
)


def handle_show(args: argparse.Namespace) -> int:
    """Resolve and render one xprompt definition."""
    normalize_show_name(args.name)
    result = resolve_show_record(args.name, project=args.project)
    if isinstance(result, ShowLookupMiss):
        _print_lookup_miss(result)
        return 1

    if args.format == "json":
        _print_warnings(result.warnings)
        json.dump(result.to_json_dict(), sys.stdout, indent=2)
        sys.stdout.write("\n")
        return 0

    if args.format == "raw":
        _print_warnings(result.warnings)
        if result.raw is None:
            print(
                f"raw definition unavailable for {result.reference}",
                file=sys.stderr,
            )
            return 2
        sys.stdout.write(result.raw)
        return 0

    use_color = resolve_color(args.color)
    render_show(result, console=_console(use_color=use_color))
    return 0


def _print_lookup_miss(miss: ShowLookupMiss) -> None:
    print(f"unknown xprompt: {miss.name}", file=sys.stderr)
    if not miss.suggestions:
        return
    print("suggestions:", file=sys.stderr)
    for suggestion in miss.suggestions:
        print(f"  {suggestion}", file=sys.stderr)


def _print_warnings(warnings: list[str]) -> None:
    for warning in warnings:
        print(warning, file=sys.stderr)


def _console(*, use_color: bool) -> Console:
    width = shutil.get_terminal_size((100, 24)).columns if sys.stdout.isatty() else 100
    return Console(
        no_color=not use_color,
        force_terminal=use_color,
        color_system="256",
        width=width,
        markup=False,
        emoji=False,
        highlight=False,
    )


__all__ = ["handle_show"]
