"""Argument parser definition for the ``sase file-hook`` command group."""

from __future__ import annotations

import argparse


def register_file_hook_parser(subparsers: argparse._SubParsersAction) -> None:
    """Register the ``sase file-hook`` command group."""
    file_hook_parser = subparsers.add_parser(
        "file-hook",
        help="Inspect configured per-file repository hooks",
        description=(
            "Inspect non-gating commands configured under `file_hooks` and "
            "the producer audit history for matching, dispatch, and "
            "pre-run failures. With no subcommand, `sase file-hook` "
            "defaults to `sase file-hook list`."
        ),
        epilog=(
            "examples:\n"
            "  sase file-hook\n"
            "  sase file-hook list\n"
            "  sase file-hook list --json\n"
            "  sase file-hook history\n"
            "  sase file-hook show 1a2b3c"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    file_hook_subparsers = file_hook_parser.add_subparsers(
        dest="file_hook_subcommand",
        help="File-hook subcommands",
        metavar="<subcommand>",
        title="subcommands",
    )

    exec_batch_parser = file_hook_subparsers.add_parser(
        "exec-batch",
        help=argparse.SUPPRESS,
    )
    file_hook_subparsers._choices_actions = [
        action
        for action in file_hook_subparsers._choices_actions
        if action.dest != "exec-batch"
    ]
    exec_batch_parser.add_argument(
        "batch",
        help=argparse.SUPPRESS,
    )

    history_parser = file_hook_subparsers.add_parser(
        "history",
        help="Show recent producer dispatch audits",
        description=(
            "List producer-side file-hook outcomes newest first: dispatched "
            "batches, filter misses, no configured hooks, and producer "
            "failures. Command-run failures still live on batch run logs; "
            "this surface is the pre-run evidence. This is not the default "
            "for bare `sase file-hook`."
        ),
    )
    history_parser.add_argument(
        "-j",
        "--json",
        action="store_true",
        help="Emit deterministic machine-readable JSON",
    )
    history_parser.add_argument(
        "-n",
        "--limit",
        type=int,
        default=20,
        metavar="N",
        help="Maximum number of audits to show (default: 20; 0 means all)",
    )

    list_parser = file_hook_subparsers.add_parser(
        "list",
        help="List effective file hooks and their config sources",
        description=(
            "List every valid effective file hook with its command, filters, "
            "timeout, description, and contributing config layer. Invalid "
            "entries are warned about and skipped. This is also the default "
            "for bare `sase file-hook`."
        ),
    )
    list_parser.add_argument(
        "-j",
        "--json",
        action="store_true",
        help="Emit deterministic machine-readable JSON",
    )

    show_parser = file_hook_subparsers.add_parser(
        "show",
        help="Show one producer dispatch audit",
        description=(
            "Print one producer audit by exact id or unique prefix so an "
            "operator can tell whether an event was unmatched, dispatched, "
            "or failed before a hook command ran."
        ),
    )
    show_parser.add_argument(
        "audit_id",
        help="Producer audit id, or a unique prefix of that id",
    )
    show_parser.add_argument(
        "-j",
        "--json",
        action="store_true",
        help="Emit deterministic machine-readable JSON",
    )


__all__ = ["register_file_hook_parser"]
