"""Handler for the ``sase vcs`` CLI subcommand."""

from __future__ import annotations

import argparse
import os
import sys


def _handle_list(args: argparse.Namespace) -> int:
    """Render the resolved repository constellation."""
    from sase.vcs_list.collect import run_vcs_list
    from sase.vcs_list.render import render

    result = run_vcs_list(
        cwd=os.getcwd(),
        repo_filters=args.repos,
        current_only=args.current_only,
        no_fetch=args.no_fetch,
        sort=args.sort,
    )
    render(result, fmt=args.format, color=args.color)
    return 0 if result.repos else 1


def _handle_log(args: argparse.Namespace) -> int:
    """Render the cross-repository commit timeline.

    Exits ``0`` when at least one repo was read (even if it had no commits);
    ``1`` when nothing readable was found (e.g. the current directory is not
    a SASE workspace or a VCS repository). Warnings are surfaced in every
    format.
    """
    from sase.vcs_log.collect import run_vcs_log
    from sase.vcs_log.dates import VcsLogDateError, parse_time_bound
    from sase.vcs_log.models import CommitFilters
    from sase.vcs_log.progress import make_fetch_progress
    from sase.vcs_log.render import render

    try:
        since = parse_time_bound(args.since) if args.since else None
        until = parse_time_bound(args.until) if args.until else None
    except VcsLogDateError as exc:
        print(f"sase vcs log: {exc}", file=sys.stderr)
        return 2

    if since is not None and until is not None and since > until:
        print(
            "sase vcs log: --since/--after must be at or before --until/--before",
            file=sys.stderr,
        )
        return 2

    filters = CommitFilters(
        since=since,
        until=until,
        authors=tuple(args.authors or ()),
    )

    result = run_vcs_log(
        cwd=os.getcwd(),
        limit=args.limit,
        filters=filters,
        repo_filters=args.repos,
        all_projects=args.all,
        current_only=args.current_only,
        include_sidecars=args.sdd,
        no_fetch=args.no_fetch,
        force_fetch=args.force_fetch,
        remote_ref=args.remote_ref,
        fetch_progress=make_fetch_progress(args.color),
    )
    render(
        result,
        fmt=args.format,
        color=args.color,
        limit=args.limit,
        filters=filters,
        reverse=args.reverse,
        show_tags=args.show_tags,
        all_projects=args.all,
    )
    return 0 if result.repos else 1


_HANDLERS = {
    "list": _handle_list,
    "log": _handle_log,
}


def handle_vcs_command(args: argparse.Namespace) -> None:
    """Dispatch a parsed ``sase vcs ...`` command to its handler."""
    sub = getattr(args, "vcs_subcommand", None)
    handler = _HANDLERS.get(sub) if isinstance(sub, str) else None
    if handler is None:
        print("Usage: sase vcs {list,log}", file=sys.stderr)
        sys.exit(2)
    sys.exit(handler(args))
