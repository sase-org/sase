"""Argument parser definitions for the ``sase sudo`` command group."""

from __future__ import annotations

import argparse


SUDO_DOCS_URL = "https://sase.sh/sudo/"


def register_sudo_parser(subparsers: argparse._SubParsersAction) -> None:
    """Register the ``sudo`` command group."""
    sudo_parser = subparsers.add_parser(
        "sudo",
        help="Request, inspect, and answer typed sudo gates",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        description=(
            "Create typed sudo request gates and answer them from a controlling "
            "terminal through the dedicated sudo runner."
        ),
        epilog=(
            "With no subcommand, `sase sudo` defaults to `sase sudo list`.\n"
            f"docs: {SUDO_DOCS_URL}"
        ),
    )
    sudo_subparsers = sudo_parser.add_subparsers(
        dest="sudo_subcommand",
        help="Sudo subcommands",
    )
    _register_answer(sudo_subparsers)
    _register_exec(sudo_subparsers)
    _register_finalize(sudo_subparsers)
    _register_list(sudo_subparsers)
    _register_request(sudo_subparsers)
    _register_show(sudo_subparsers)


def _register_answer(subparsers: argparse._SubParsersAction) -> None:
    parser = subparsers.add_parser(
        "answer",
        help="Approve or deny one sudo gate",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "examples:\n"
            "  sase sudo answer sudo-123 --run\n"
            "  sase sudo answer sudo-123 --run --detach\n"
            "  sase sudo answer sudo-123 --run --command refresh\n"
            "  sase sudo answer sudo-123 --deny --feedback 'not needed'\n"
            "  sase sudo answer sudo-123 --json --run\n"
            f"\ndocs: {SUDO_DOCS_URL}"
        ),
    )
    parser.add_argument("gate_ref", metavar="ID", help="Sudo gate id or shell ref")
    choice = parser.add_mutually_exclusive_group()
    choice.add_argument("-a", "--approve", action="store_true", help="Approve and run")
    parser.add_argument(
        "-c",
        "--command",
        action="append",
        default=None,
        dest="sudo_command",
        metavar="ID",
        help="Reviewed command id to run; repeat to select a subset",
    )
    choice.add_argument("-d", "--deny", action="store_true", help="Deny")
    detach = parser.add_mutually_exclusive_group()
    detach.add_argument(
        "-D",
        "--detach",
        action="store_true",
        help=(
            "Authenticate on this TTY, then run the reviewed commands in a "
            "supervised background proc; the gate stays pending until that "
            "proc finishes"
        ),
    )
    parser.add_argument("-f", "--feedback", default=None, help="Reviewer note")
    parser.add_argument("-j", "--json", action="store_true", help="Emit JSON")
    detach.add_argument(
        "-N",
        "--no-detach",
        action="store_true",
        help="Authenticate and run in the foreground (the current default)",
    )
    retry = parser.add_mutually_exclusive_group()
    retry.add_argument(
        "-R", "--restart", action="store_true", help="Restart a partial attempt"
    )
    retry.add_argument(
        "-r", "--resume", action="store_true", help="Resume a partial attempt"
    )
    choice.add_argument("-u", "--run", action="store_true", help="Authenticate and run")


def _register_list(subparsers: argparse._SubParsersAction) -> None:
    parser = subparsers.add_parser(
        "list",
        help="List sudo gate shells",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "examples:\n"
            "  sase sudo list\n"
            "  sase sudo list --all --json\n"
            f"\ndocs: {SUDO_DOCS_URL}"
        ),
    )
    parser.add_argument(
        "-a", "--all", action="store_true", help="Include settled gates"
    )
    parser.add_argument("-j", "--json", action="store_true", help="Emit JSON")
    parser.add_argument("-l", "--limit", type=int, default=None, help="Limit rows")
    parser.add_argument("-p", "--project", default=None, help="Filter by project")


def _register_finalize(subparsers: argparse._SubParsersAction) -> None:
    from sase.ops.cli import add_operation_io_flags

    parser = subparsers.add_parser(
        "finalize",
        help=argparse.SUPPRESS,
        description="Internal detached sudo finalizer.",
    )
    parser.add_argument("gate_ref", metavar="ID", help=argparse.SUPPRESS)
    parser.add_argument("-j", "--json", action="store_true", help=argparse.SUPPRESS)
    add_operation_io_flags(parser)


def _register_exec(subparsers: argparse._SubParsersAction) -> None:
    parser = subparsers.add_parser(
        "exec",
        help=argparse.SUPPRESS,
        description="Internal target-side sudo execution entrypoint.",
    )
    parser.add_argument("--contract", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--detach", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--expected-sha256", metavar="SHA256", help=argparse.SUPPRESS)
    parser.add_argument("--handshake", metavar="PATH", help=argparse.SUPPRESS)
    parser.add_argument("--ledger", metavar="PATH", help=argparse.SUPPRESS)
    parser.add_argument("--manifest", metavar="PATH", help=argparse.SUPPRESS)


def _register_request(subparsers: argparse._SubParsersAction) -> None:
    parser = subparsers.add_parser(
        "request",
        help="Create a sudo gate from one JSON object on stdin",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "examples:\n"
            '  printf \'%s\' \'{"reason":"install package","commands":[{"id":"apt","argv":["/usr/bin/apt-get","update"]}]}\' | sase sudo request\n'
            "  sase sudo request --json < sudo-request.json\n"
            f"\ndocs: {SUDO_DOCS_URL}"
        ),
    )
    parser.add_argument("-j", "--json", action="store_true", help="Emit JSON")
    parser.add_argument(
        "-o", "--origin-agent", default=None, help="Attribute the request"
    )


def _register_show(subparsers: argparse._SubParsersAction) -> None:
    parser = subparsers.add_parser(
        "show",
        help="Show a sudo gate",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "examples:\n"
            "  sase sudo show sudo-123\n"
            "  sase sudo show sudo-123 --json\n"
            f"\ndocs: {SUDO_DOCS_URL}"
        ),
    )
    parser.add_argument("gate_ref", metavar="ID", help="Sudo gate id or shell ref")
    parser.add_argument("-j", "--json", action="store_true", help="Emit JSON")


__all__ = ["SUDO_DOCS_URL", "register_sudo_parser"]
