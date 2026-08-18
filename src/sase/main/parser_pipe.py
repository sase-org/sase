"""Argument parser definition for the ``sase pipe`` CLI command."""

from __future__ import annotations

import argparse


def register_pipe_parser(subparsers: argparse._SubParsersAction) -> None:
    """Register the in-process family-successor hand-off command."""
    pipe_parser = subparsers.add_parser(
        "pipe",
        usage="sase pipe [-h] [-f] [-j] [-m MODEL] [-n TOKEN] [-r TEXT] PROMPT",
        help="Hand this agent's turn to the next family member and end this turn",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        description=(
            "End this agent's turn and continue the run as the next family "
            "member in the same workspace, with the prompt you write. This is "
            "not a launch, a monitor, or fan-out: one successor, serially, in "
            "the same process. This command kills the calling agent; say "
            "everything the successor needs inside PROMPT."
        ),
        epilog=(
            "This ends your turn. The process does not return after a "
            "successful hand-off.\n"
            "\n"
            "example:\n"
            "  sase pipe 'implement the approved plan' --reason "
            "'hand off to a coding pass' --model opus"
        ),
    )
    pipe_parser.add_argument(
        "prompt",
        metavar="PROMPT",
        help="Full successor prompt; %% directives and # references stay live",
    )
    pipe_parser.add_argument(
        "-f",
        "--fresh",
        action="store_true",
        help=(
            "Successor starts with a clean context window (default: prefix "
            "#fork:<this agent> so it inherits this chat)"
        ),
    )
    pipe_parser.add_argument(
        "-j",
        "--json",
        action="store_true",
        help="Print a machine-readable hand-off summary instead of the rich one",
    )
    pipe_parser.add_argument(
        "-m",
        "--model",
        default=None,
        metavar="MODEL",
        help=(
            "Model or alias for the successor (opus, opus@high, sonnet, "
            "codex/gpt-5). Default: inherit this agent's model"
        ),
    )
    pipe_parser.add_argument(
        "-n",
        "--name",
        default=None,
        metavar="TOKEN",
        help=(
            "Successor role token: review yields <family>--review. Default: "
            "the next free numbered member (--@)"
        ),
    )
    pipe_parser.add_argument(
        "-r",
        "--reason",
        default=None,
        metavar="TEXT",
        help="One-line reason, recorded on the successor and shown in agent lists",
    )
