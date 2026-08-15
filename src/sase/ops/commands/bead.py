"""Noninteractive bead status runner."""

from __future__ import annotations

import argparse
from collections.abc import Mapping

from sase.ops.cli import add_operation_io_flags
from sase.ops.commands.common import run_and_finish
from sase.ops.names import BEAD_STATUS


def add_bead_operation_parsers(subparsers: argparse._SubParsersAction) -> None:
    """Register the focused bead status command."""
    parser = subparsers.add_parser(
        "apply-status",
        help="Set one bead's status through the bead store mutation path",
        description=(
            "Apply a status update to one bead. The bead id and status are "
            "positional. When run as a durable proc, the typed result is "
            "written to the configured result sidecar."
        ),
    )
    parser.add_argument("bead_id", help="Full or shorthand bead id")
    parser.add_argument("status", help="New bead status")
    add_operation_io_flags(parser)


def handle_bead_operation(args: argparse.Namespace) -> int:
    """Dispatch the bead apply-status command."""
    if getattr(args, "bead_subcommand", None) != "apply-status":
        return 2
    return run_and_finish(
        operation=BEAD_STATUS,
        body=lambda: _run_apply_status(args),
        args=args,
    )


def _run_apply_status(
    args: argparse.Namespace,
) -> tuple[bool, str, Mapping[str, object]]:
    from sase.bead.cli_common import auto_commit_bead_store, bead_store_mutation

    with bead_store_mutation(auto_commit_bead_store) as mutation:
        updated = mutation.project.update(args.bead_id, status=args.status)
        mutation.commit(f"Update {updated.id} status to {args.status}")
    return (
        True,
        f"Updated {updated.id} status to {args.status}",
        {"bead_id": updated.id, "status": args.status},
    )


__all__ = ["add_bead_operation_parsers", "handle_bead_operation"]
