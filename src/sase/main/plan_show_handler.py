"""Handler for ``sase plan show``."""

from __future__ import annotations

import argparse
import json
import shutil
import sys
from pathlib import Path

from rich.console import Console

from sase.bead.cli_dep_render import resolve_color
from sase.main.parser_bead_common import resolve_wrap_width
from sase.main.plan_show_render import (
    print_ambiguity,
    print_miss,
    render_compact,
    render_full,
)
from sase.plan_show.model import PlanShowAmbiguity, PlanShowMiss, PlanShowRecord
from sase.plan_show.resolve import resolve_plan_show_target


def handle_plan_show_command(args: argparse.Namespace) -> int:
    """Resolve and render one plan; return the intended process exit code."""
    result = resolve_plan_show_target(
        args.target,
        target_kind=args.target_kind,
        cwd=Path.cwd(),
    )
    if isinstance(result, PlanShowMiss):
        print_miss(result)
        return 1
    if isinstance(result, PlanShowAmbiguity):
        print_ambiguity(result)
        return 1

    if args.format == "raw":
        return _print_raw(result)
    if args.format == "json":
        json.dump(result.to_json_dict(), sys.stdout, indent=2, default=str)
        sys.stdout.write("\n")
        return 0

    console = _console(use_color=resolve_color(args.color))
    if args.format == "compact":
        render_compact(result, console=console)
    else:
        render_full(result, console=console, wrap=resolve_wrap_width(args.wrap))
    return 0


def _print_raw(record: PlanShowRecord) -> int:
    try:
        text = Path(record.plan.path).read_text(encoding="utf-8")
    except OSError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1
    sys.stdout.write(text)
    return 0


def _console(*, use_color: bool) -> Console:
    # Only ``always`` sets ``force_terminal``/``color_system``: the shared
    # ``plan_display`` renderers always attach real style strings, so a
    # ``never`` console must rely on ``is_terminal`` staying False (a bare
    # ``no_color=True`` alone would still let bold/dim SGR codes through).
    width = shutil.get_terminal_size((100, 24)).columns if sys.stdout.isatty() else 100
    kwargs: dict[str, object] = {
        "width": width,
        "markup": False,
        "emoji": False,
        "highlight": False,
    }
    if use_color:
        kwargs.update(force_terminal=True, no_color=False, color_system="256")
    else:
        kwargs.update(no_color=True)
    return Console(**kwargs)  # type: ignore[arg-type]


__all__ = ["handle_plan_show_command"]
