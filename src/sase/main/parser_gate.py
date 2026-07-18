"""Argument parser definitions for the ``sase gate`` command group."""

from __future__ import annotations

import argparse


def register_gate_parser(subparsers: argparse._SubParsersAction) -> None:
    """Register the ``gate`` subcommand parser."""
    gate_parser = subparsers.add_parser(
        "gate",
        help="Create or wait for durable command-backed gates",
        description=(
            "Create durable command-backed gates from versioned JSON specifications "
            "and wait mechanically for their terminal results."
        ),
    )
    gate_subparsers = gate_parser.add_subparsers(
        dest="gate_subcommand",
        help="Gate subcommands",
    )

    create_parser = gate_subparsers.add_parser(
        "create",
        help="Create a durable gate from a JSON specification on stdin",
        description=(
            "Read a schema-versioned gate specification from stdin, create its "
            "verified action bundle and notification, then emit a stable JSON "
            "descriptor containing the gate kind and request id."
        ),
        epilog=(
            "examples:\n"
            "  sase gate create < gate-request.json\n"
            "  sase gate create --sender deploy-review --tag production "
            "< gate-request.json"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    create_parser.add_argument(
        "-s",
        "--sender",
        default=None,
        help="Override the notification sender in the gate presentation",
    )
    create_parser.add_argument(
        "-t",
        "--tag",
        action="append",
        default=None,
        help="Add a notification tag to the gate presentation; repeat to add more",
    )

    wait_parser = gate_subparsers.add_parser(
        "wait",
        help="Wait mechanically for a durable gate to reach a terminal state",
        description=(
            "Wait for a durable gate identified by the kind and request id emitted "
            "by `sase gate create`. The gate's configured timeout always applies; "
            "--timeout may impose an earlier caller deadline."
        ),
        epilog=(
            "terminal exit codes:\n"
            "  0  answered\n"
            "  3  cancelled\n"
            "  4  timeout\n\n"
            "examples:\n"
            "  sase gate wait --id custom-123 --kind custom\n"
            "  sase gate wait -i custom-123 -k custom --json\n"
            "  sase gate wait -i custom-123 -k custom --timeout 60"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    wait_parser.add_argument(
        "-i",
        "--id",
        required=True,
        metavar="REQUEST_ID",
        help="Gate request id from the creation descriptor",
    )
    wait_parser.add_argument(
        "-j",
        "--json",
        action="store_true",
        help="Emit the stable machine-readable terminal result",
    )
    wait_parser.add_argument(
        "-k",
        "--kind",
        required=True,
        help="Gate kind from the creation descriptor",
    )
    wait_parser.add_argument(
        "-t",
        "--timeout",
        type=float,
        default=None,
        metavar="SECONDS",
        help="Stop waiting after this many seconds, without extending the gate timeout",
    )


__all__ = ["register_gate_parser"]
