"""Handler for ``sase plan search``.

Validate the parsed CLI args, call the :mod:`sase.plan_search` facade, and
render the results. The Rust core owns discovery/filtering/ranking; this handler
only gates the inputs, picks the format, and hands off to the renderer.

``--format json`` is serialized here; the colored ``compact``/``full`` and the
agent-friendly ``markdown`` formats are produced by :mod:`sase.main.
plan_search_render`.
"""

from __future__ import annotations

import argparse
import dataclasses
import json
import re
import sys
from collections.abc import Sequence
from typing import NoReturn

from sase.plan_search.model import PlanSearchMatch

# Accepted DATE forms for ``--since``/``--until``: ``YYYY-MM-DD``, ``YYYY-MM``,
# ``YYYYMM``, or a relative ``Nd``/``Nw``/``Nm`` offset (e.g. ``14d``, ``2w``,
# ``3m``). The Rust core does the real parsing/arithmetic; this is a syntactic
# gate so malformed input is rejected with a clear CLI error instead of
# surfacing as an opaque binding failure.
_DATE_PATTERNS = (
    re.compile(r"^\d{4}-\d{2}-\d{2}$"),
    re.compile(r"^\d{4}-\d{2}$"),
    re.compile(r"^\d{6}$"),
    re.compile(r"^\d+[dwm]$"),
)

_DATE_HELP = "YYYY-MM-DD, YYYY-MM, YYYYMM, or a relative offset like 14d / 2w / 3m"


def _is_valid_plan_date(value: str) -> bool:
    """Return whether ``value`` matches one of the accepted DATE forms."""
    return any(pattern.match(value) for pattern in _DATE_PATTERNS)


def plan_date_arg(value: str) -> str:
    """``argparse`` type validating a ``--since``/``--until`` DATE argument."""
    if not _is_valid_plan_date(value):
        raise argparse.ArgumentTypeError(
            f"invalid date {value!r}; expected {_DATE_HELP}"
        )
    return value


def handle_plan_search_command(args: argparse.Namespace) -> None:
    """Validate args, run the plan search, and render the result."""
    from sase.plan_search import facade

    _validate_args(args, valid_kinds=facade.available_kinds())

    matches = facade.search(
        args.query,
        kinds=args.kind,
        statuses=args.status,
        source=args.source,
        since=args.since,
        until=args.until,
        sort=args.sort,
        limit=args.limit,
    )

    if args.format == "json":
        print(_render_search_json(matches, args.query), end="")
        return

    from sase.main.plan_search_render import render as render_plan_search

    render_plan_search(
        matches,
        query=args.query,
        fmt=args.format,
        color=args.color,
        sort_label=_effective_sort_label(args),
    )


def _effective_sort_label(args: argparse.Namespace) -> str:
    """The sort actually applied: ``--sort`` if given, else the query default."""
    if args.sort:
        return str(args.sort)
    return "relevance" if (args.query and args.query.strip()) else "recent"


def _validate_args(
    args: argparse.Namespace,
    *,
    valid_kinds: Sequence[str] | None = None,
) -> None:
    """Re-validate limit and date args defensively before searching.

    The parser enforces these via ``nonnegative_int`` / :func:`plan_date_arg`,
    but the handler owns input validation too so a directly-constructed
    ``Namespace`` (or a future caller) still fails fast with a clear message.
    """
    if args.limit is not None and args.limit < 0:
        _usage_error(f"invalid limit {args.limit}; must be a non-negative integer")
    for flag, value in (("--since", args.since), ("--until", args.until)):
        if value is not None and not _is_valid_plan_date(value):
            _usage_error(f"invalid {flag} date {value!r}; expected {_DATE_HELP}")
    if valid_kinds is not None and args.kind:
        valid = tuple(dict.fromkeys(valid_kinds))
        invalid = tuple(kind for kind in args.kind if kind not in valid)
        if invalid:
            invalid_label = ", ".join(repr(kind) for kind in invalid)
            _usage_error(
                f"invalid --kind {invalid_label}; valid values for the current "
                f"project: {', '.join(valid)}"
            )


def _render_search_json(matches: list[PlanSearchMatch], query: str | None) -> str:
    envelope = {
        "query": query or "",
        "count": len(matches),
        "results": [
            {
                "plan": dataclasses.asdict(match.plan),
                "matched_fields": match.matched_fields,
                "score": match.score,
            }
            for match in matches
        ],
    }
    return json.dumps(envelope, indent=2) + "\n"


def _usage_error(message: str) -> NoReturn:
    print(f"Error: {message}", file=sys.stderr)
    sys.exit(2)


__all__ = [
    "handle_plan_search_command",
    "plan_date_arg",
]
