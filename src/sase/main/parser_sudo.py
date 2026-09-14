"""Argument parser definitions for the ``sase sudo`` command group."""

from __future__ import annotations

import argparse


def register_sudo_parser(subparsers: argparse._SubParsersAction) -> None:
    """Register the ``sudo`` command group."""
    sudo_parser = subparsers.add_parser(
        "sudo",
        help="Request, inspect, and answer typed sudo gates",
        description=(
            "Create typed sudo request gates and answer them from a controlling "
            "terminal through the dedicated sudo runner."
        ),
    )
    sudo_subparsers = sudo_parser.add_subparsers(
        dest="sudo_subcommand",
        help="Sudo subcommands",
    )
    _register_answer(sudo_subparsers)
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
            "  sase sudo answer sudo-123 --approve\n"
            "  sase sudo answer sudo-123 --deny --feedback 'not needed'\n"
            "  sase sudo answer sudo-123 --json --approve"
        ),
    )
    parser.add_argument("gate_ref", metavar="ID", help="Sudo gate id or shell ref")
    choice = parser.add_mutually_exclusive_group()
    choice.add_argument("-a", "--approve", action="store_true", help="Approve")
    choice.add_argument("-d", "--deny", action="store_true", help="Deny")
    parser.add_argument("-f", "--feedback", default=None, help="Reviewer note")
    parser.add_argument("-j", "--json", action="store_true", help="Emit JSON")
    retry = parser.add_mutually_exclusive_group()
    retry.add_argument(
        "-r", "--resume", action="store_true", help="Resume a partial attempt"
    )
    retry.add_argument(
        "-R", "--restart", action="store_true", help="Restart a partial attempt"
    )


def _register_list(subparsers: argparse._SubParsersAction) -> None:
    parser = subparsers.add_parser(
        "list",
        help="List sudo gate shells",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="examples:\n  sase sudo list\n  sase sudo list --all --json",
    )
    parser.add_argument(
        "-a", "--all", action="store_true", help="Include settled gates"
    )
    parser.add_argument("-j", "--json", action="store_true", help="Emit JSON")
    parser.add_argument("-l", "--limit", type=int, default=None, help="Limit rows")
    parser.add_argument("-p", "--project", default=None, help="Filter by project")


def _register_request(subparsers: argparse._SubParsersAction) -> None:
    parser = subparsers.add_parser(
        "request",
        help="Create a sudo gate from one JSON object on stdin",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "examples:\n"
            '  printf \'%s\' \'{"reason":"install package","commands":[{"id":"apt","argv":["/usr/bin/apt-get","update"]}]}\' | sase sudo request\n'
            "  sase sudo request --json < sudo-request.json"
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
        epilog="examples:\n  sase sudo show sudo-123\n  sase sudo show sudo-123 --json",
    )
    parser.add_argument("gate_ref", metavar="ID", help="Sudo gate id or shell ref")
    parser.add_argument("-j", "--json", action="store_true", help="Emit JSON")


__all__ = ["register_sudo_parser"]
