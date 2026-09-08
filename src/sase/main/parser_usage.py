"""Argument parser definition for the ``sase usage`` CLI command."""

from __future__ import annotations

import argparse

from sase.completion.kinds import ValueKind, set_completion_kind


def register_usage_parser(subparsers: argparse._SubParsersAction) -> None:
    """Register cached subscription-usage inspection commands."""
    usage_parser = subparsers.add_parser(
        "usage",
        help="Inspect and refresh cached LLM subscription usage",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        description=(
            "Inspect cached provider subscription-usage observations and submit "
            "explicit refreshes. Running `sase usage` defaults to "
            "`sase usage list`. The list command never calls provider CLIs or "
            "APIs; use `sase usage refresh` to submit bounded refresh work."
        ),
        epilog=(
            "examples:\n"
            "  sase usage\n"
            "  sase usage list -p codex\n"
            "  sase usage list --json\n"
            "  sase usage refresh -p codex\n"
            "  sase usage refresh --background --json"
        ),
    )
    usage_sub = usage_parser.add_subparsers(
        dest="usage_subcommand",
        help="Usage subcommands",
    )

    list_parser = usage_sub.add_parser(
        "list",
        help="List cached subscription usage without probing providers",
        description=(
            "Render the cached subscription-usage snapshot. This command is "
            "strictly offline and does not start AXE, log in, or call provider "
            "CLIs. Missing observations are reported as data."
        ),
    )
    _add_common_usage_options(list_parser)

    refresh_parser = usage_sub.add_parser(
        "refresh",
        help="Submit explicit subscription-usage refresh work",
        description=(
            "Submit bounded durable refresh work for provider subscription usage. "
            "By default this waits for submitted or joined work and then renders "
            "the refreshed cache. Use --background to return after submission."
        ),
    )
    refresh_parser.add_argument(
        "-b",
        "--background",
        action="store_true",
        help="Submit or join refresh work and return without waiting",
    )
    _add_common_usage_options(refresh_parser)


def _add_common_usage_options(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "-j",
        "--json",
        action="store_true",
        help="Emit one stable JSON document",
    )
    parser.add_argument(
        "-P",
        "--plain",
        action="store_true",
        help="Emit undecorated line-oriented text",
    )
    provider_action = parser.add_argument(
        "-p",
        "--provider",
        action="append",
        default=[],
        metavar="PROVIDER",
        help="Filter to one provider; repeatable",
    )
    set_completion_kind(provider_action, ValueKind.PROVIDER)
    parser.add_argument(
        "-v",
        "--verbose",
        action="store_true",
        help="Show source, diagnostic, and exact timestamp details",
    )


__all__ = ["register_usage_parser"]
