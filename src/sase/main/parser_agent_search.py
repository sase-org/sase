"""Argument parser definition for ``sase agent search``."""

from __future__ import annotations

import argparse

DEFAULT_AGENT_SEARCH_LIMIT = 40


def _nonnegative_limit(value: str) -> int:
    try:
        parsed = int(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError(
            "limit must be a non-negative integer"
        ) from exc
    if parsed < 0:
        raise argparse.ArgumentTypeError("limit must be a non-negative integer")
    return parsed


def register_agent_search_parser(agents_sub: argparse._SubParsersAction) -> None:
    """Register the 'sase agent search' subcommand."""
    search_parser = agents_sub.add_parser(
        "search",
        help="Search the agent catalog or archive",
        description=(
            "Search the historical agent catalog using the same boolean query "
            "dialect as the Artifacts -> Agent pane. Without an in: token, "
            "search keeps the catalog behavior. Use in:inbox for non-dismissed "
            "catalog rows or in:archive for the shared dismissed archive corpus."
        ),
        epilog=(
            "examples:\n"
            "  sase agent search\n"
            "  sase agent search 'revivable:true AND project:sase AND role:code'\n"
            "  sase agent search 'provider:codex AND status:FAILED AND since:7d'\n"
            "  sase agent search 'session:\"research.12\" AND NOT kind:workflow-child'\n"
            "  sase agent search 'state:active AND (attention:true OR status:WAITING)'\n"
            "  sase agent search 'linked:true AND relation:read'\n"
            "  sase agent search 'retry:true AND model:\"gpt-6.1-sol\" AND min:5m'\n"
            "  sase agent search 'in:archive AND outcome:failed AND project:sase'\n"
            "  sase agent search 'in:inbox AND status:FAILED'\n"
            "\n"
            "in:inbox and in:archive are host-owned scope tokens. They may appear "
            "once at top level, outside NOT, OR, and parentheses. Archive-only "
            "fields such as outcome and restorable require in:archive.\n"
            "\n"
            "date bounds since/until/after/before accept Nh/Nd/Nw/Nm, today, "
            "and YYYY-MM-DD; Nm means months there. Runtime bounds min/max "
            "accept seconds or Ns/Nm/Nh/Nd; Nm means minutes there."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    search_parser.add_argument(
        "-j",
        "--json",
        action="store_true",
        help="Emit a stable machine-readable JSON array",
    )
    search_parser.add_argument(
        "-l",
        "--limit",
        metavar="LIMIT",
        type=_nonnegative_limit,
        default=None,
        help=f"Cap rendered rows; 0 means all (default: {DEFAULT_AGENT_SEARCH_LIMIT})",
    )
    search_parser.add_argument(
        "-p",
        "--project",
        metavar="PROJECT",
        help="Scope the catalog to one project key, alias, or display name",
    )
    search_parser.add_argument(
        "query",
        metavar="QUERY",
        nargs="*",
        help="Boolean agent-catalog query; may include a limit: token",
    )


__all__ = ["DEFAULT_AGENT_SEARCH_LIMIT", "register_agent_search_parser"]
