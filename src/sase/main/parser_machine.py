"""Argument parser for ``sase machine`` remote enrollment commands."""

from __future__ import annotations

import argparse

from sase.ops.cli import add_operation_io_flags


def register_machine_parser(subparsers: argparse._SubParsersAction) -> None:
    """Register the ``machine`` command group."""
    parser = subparsers.add_parser(
        "machine",
        help="Manage enrolled remote machines",
        description=(
            "Manage viewer-local aliases for enrolled remote machines. With no "
            "subcommand, delegates to `sase machine list`."
        ),
    )
    machine_subparsers = parser.add_subparsers(
        dest="machine_subcommand",
        help="Machine subcommands",
    )

    add_parser = machine_subparsers.add_parser(
        "add",
        help="Enroll a remote machine alias",
        description=(
            "Enroll ALIAS against ENDPOINT using a pasted enrollment bundle. "
            "The bundle is read from --bootstrap-file or an interactive prompt; "
            "no secret value is accepted as a command-line option."
        ),
    )
    add_parser.add_argument("alias", metavar="ALIAS", help="Viewer-local alias")
    add_parser.add_argument(
        "endpoint",
        nargs="?",
        metavar="ENDPOINT",
        help="HTTPS fleet gateway endpoint",
    )
    add_parser.add_argument(
        "-B",
        "--bootstrap-file",
        metavar="PATH",
        help="Read the enrollment bundle from PATH instead of prompting",
    )
    add_parser.add_argument(
        "-c",
        "--candidate",
        metavar="REF",
        help="Use a discovered candidate key formatted as PROVIDER|ENDPOINT",
    )
    add_parser.add_argument(
        "-j",
        "--json",
        action="store_true",
        help="Emit a schema-versioned JSON result",
    )
    add_parser.add_argument(
        "-p",
        "--provider",
        metavar="PROVIDER",
        default="builtin@https",
        help="Dispatch provider ref to store with the alias",
    )
    add_parser.add_argument(
        "-t",
        "--timeout",
        type=float,
        metavar="SECONDS",
        help="Per-request gateway timeout in seconds",
    )

    agent_parser = machine_subparsers.add_parser(
        "agent",
        help="Stop, retry, or fork a remote agent on its owning host",
        description=(
            "Submit a journaled lifecycle mutation for a remote agent. ALIAS is "
            "the enrolled machine; AGENT identifies the exact remote row. ACE "
            "supplies locator, revision, and operation key through the durable "
            "request sidecar."
        ),
    )
    agent_subparsers = agent_parser.add_subparsers(
        dest="machine_agent_subcommand",
        help="Remote agent actions",
    )
    fork_parser = agent_subparsers.add_parser(
        "fork",
        help="Fork a remote agent on its owning host",
        description=(
            "Fork AGENT on ALIAS with INSTRUCTION. The fork runs on the target "
            "through its own launch machinery."
        ),
    )
    fork_parser.add_argument("alias", metavar="ALIAS", help="Enrolled machine alias")
    fork_parser.add_argument("agent", metavar="AGENT", help="Remote agent name")
    fork_parser.add_argument(
        "instruction",
        nargs="?",
        metavar="INSTRUCTION",
        help=(
            "Fork instruction appended to #fork:<name>. Optional when ACE "
            "supplies it through the durable request sidecar."
        ),
    )
    fork_parser.add_argument(
        "-j",
        "--json",
        action="store_true",
        help="Emit a schema-versioned JSON result",
    )
    fork_parser.add_argument(
        "-t",
        "--timeout",
        type=float,
        metavar="SECONDS",
        help="Per-request gateway timeout in seconds",
    )
    add_operation_io_flags(fork_parser)

    retry_parser = agent_subparsers.add_parser(
        "retry",
        help="Retry remote agents on their owning host",
        description="Retry one or more remote agents on ALIAS.",
    )
    retry_parser.add_argument("alias", metavar="ALIAS", help="Enrolled machine alias")
    retry_parser.add_argument(
        "agents",
        nargs="+",
        metavar="AGENT",
        help="Remote agent names",
    )
    retry_parser.add_argument(
        "-j",
        "--json",
        action="store_true",
        help="Emit a schema-versioned JSON result",
    )
    retry_parser.add_argument(
        "-t",
        "--timeout",
        type=float,
        metavar="SECONDS",
        help="Per-request gateway timeout in seconds",
    )
    add_operation_io_flags(retry_parser)

    stop_parser = agent_subparsers.add_parser(
        "stop",
        help="Stop remote agents on their owning host",
        description="Stop one or more remote agents on ALIAS.",
    )
    stop_parser.add_argument("alias", metavar="ALIAS", help="Enrolled machine alias")
    stop_parser.add_argument(
        "agents",
        nargs="+",
        metavar="AGENT",
        help="Remote agent names",
    )
    stop_parser.add_argument(
        "-j",
        "--json",
        action="store_true",
        help="Emit a schema-versioned JSON result",
    )
    stop_parser.add_argument(
        "-t",
        "--timeout",
        type=float,
        metavar="SECONDS",
        help="Per-request gateway timeout in seconds",
    )
    add_operation_io_flags(stop_parser)

    discover_parser = machine_subparsers.add_parser(
        "discover",
        help="Run explicit provider discovery",
        description=(
            "Ask configured and explicitly selected dispatch providers for "
            "remote-machine enrollment candidates."
        ),
    )
    discover_parser.add_argument(
        "-j",
        "--json",
        action="store_true",
        help="Emit a schema-versioned JSON result",
    )
    discover_parser.add_argument(
        "-p",
        "--provider",
        action="append",
        metavar="PROVIDER",
        help="Provider ref to discover; repeatable",
    )
    discover_parser.add_argument(
        "-t",
        "--timeout",
        type=float,
        metavar="SECONDS",
        help="Per-provider discovery timeout in seconds",
    )

    list_parser = machine_subparsers.add_parser(
        "list",
        help="List configured machine aliases without network IO",
        description="List configured remote machine aliases from local config only.",
    )
    list_parser.add_argument(
        "-j",
        "--json",
        action="store_true",
        help="Emit a schema-versioned JSON result",
    )

    remove_parser = machine_subparsers.add_parser(
        "remove",
        help="Remove a configured machine alias",
        description="Remove ALIAS from local config and delete its local credential ref.",
    )
    remove_parser.add_argument("alias", metavar="ALIAS", help="Alias to remove")
    remove_parser.add_argument(
        "-j",
        "--json",
        action="store_true",
        help="Emit a schema-versioned JSON result",
    )
    remove_parser.add_argument(
        "-y",
        "--yes",
        action="store_true",
        help="Remove without an interactive confirmation prompt",
    )

    rename_parser = machine_subparsers.add_parser(
        "rename",
        help="Rename a viewer-local machine alias",
        description=(
            "Rename OLD_ALIAS to NEW_ALIAS without changing gateway identity or "
            "credential references."
        ),
    )
    rename_parser.add_argument("old_alias", metavar="OLD_ALIAS", help="Current alias")
    rename_parser.add_argument("new_alias", metavar="NEW_ALIAS", help="New alias")
    rename_parser.add_argument(
        "-j",
        "--json",
        action="store_true",
        help="Emit a schema-versioned JSON result",
    )

    repair_parser = machine_subparsers.add_parser(
        "repair",
        help="Repair a quarantined or mismatched enrollment",
        description=(
            "Re-enroll ALIAS using a fresh one-time bundle and rotate its local "
            "credential reference."
        ),
    )
    repair_parser.add_argument("alias", metavar="ALIAS", help="Alias to repair")
    repair_parser.add_argument(
        "-B",
        "--bootstrap-file",
        metavar="PATH",
        help="Read the enrollment bundle from PATH instead of prompting",
    )
    repair_parser.add_argument(
        "-j",
        "--json",
        action="store_true",
        help="Emit a schema-versioned JSON result",
    )
    repair_parser.add_argument(
        "-t",
        "--timeout",
        type=float,
        metavar="SECONDS",
        help="Per-request gateway timeout in seconds",
    )

    status_parser = machine_subparsers.add_parser(
        "status",
        help="Run an authenticated hello check",
        description="Check configured remote machines with bounded authenticated hello calls.",
    )
    status_parser.add_argument(
        "aliases",
        nargs="*",
        metavar="ALIAS",
        help="Aliases to check; defaults to all configured aliases",
    )
    status_parser.add_argument(
        "-j",
        "--json",
        action="store_true",
        help="Emit a schema-versioned JSON result",
    )
    status_parser.add_argument(
        "-t",
        "--timeout",
        type=float,
        metavar="SECONDS",
        help="Per-request gateway timeout in seconds",
    )


__all__ = ["register_machine_parser"]
