"""Handler for the ``sase vcs`` CLI subcommand."""

from __future__ import annotations

import argparse
import os
import sys


def _handle_log(args: argparse.Namespace) -> int:
    """Render the cross-repository commit timeline.

    Exits ``0`` when at least one repo was read (even if it had no commits);
    ``1`` when nothing readable was found (e.g. the current directory is not
    a SASE workspace or a VCS repository). Warnings are surfaced in every
    format.
    """
    from sase.vcs_log.collect import run_vcs_log
    from sase.vcs_log.render import render

    result = run_vcs_log(
        cwd=os.getcwd(),
        limit=args.limit,
        repo_filters=args.repos,
        current_only=args.current_only,
    )
    render(result, fmt=args.format, color=args.color)
    return 0 if result.repos else 1


_HANDLERS = {
    "log": _handle_log,
}


def handle_vcs_command(args: argparse.Namespace) -> None:
    """Dispatch a parsed ``sase vcs ...`` command to its handler."""
    sub = getattr(args, "vcs_subcommand", None)
    handler = _HANDLERS.get(sub) if isinstance(sub, str) else None
    if handler is None:
        print("Usage: sase vcs {log}", file=sys.stderr)
        sys.exit(2)
    sys.exit(handler(args))
