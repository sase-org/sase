"""Argument parser definition for the ``sase tmux-agent`` command."""

from __future__ import annotations

import argparse

_EFFORT_CHOICES = (
    "off",
    "none",
    "minimal",
    "low",
    "medium",
    "high",
    "xhigh",
    "max",
)


def register_tmux_agent_parser(subparsers: argparse._SubParsersAction) -> None:
    """Register the ``sase tmux-agent`` command.

    This command has no subcommands — in particular no ``list`` child — so a
    bare ``sase tmux-agent`` can paint the tmux menu instead of delegating.
    """
    parser = subparsers.add_parser(
        "tmux-agent",
        help="Launch an interactive agent CLI in a new tmux window",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        description=(
            "Launch an interactive agent CLI in a new tmux window. A bare "
            "`sase tmux-agent` paints a centered tmux display-menu of every "
            "registered agent CLI; choosing a row (or passing a provider) "
            "opens a new window in the current pane's directory.\n"
            "\n"
            "There is no `list` subcommand: a bare invocation must open the "
            'menu, because the tmux key binding (`bind A run "sase '
            'tmux-agent"`) depends on that. Use `-l|--list` to print the '
            "catalog. `--renumber` is an internal hook invoked when an agent "
            "CLI window exits."
        ),
        epilog=(
            "examples:\n"
            "  sase tmux-agent                      # paint the tmux Agent menu\n"
            "  sase tmux-agent claude               # launch Claude Code directly\n"
            "  sase tmux-agent --list               # print the catalog (works outside tmux)\n"
            "  sase tmux-agent claude --dry-run     # print the exact command; change nothing\n"
            '  bind A run "sase tmux-agent"         # tmux key binding'
        ),
    )
    parser.add_argument(
        "provider",
        nargs="?",
        metavar="<provider>",
        help="Provider to launch directly (omit to paint the tmux Agent menu)",
    )
    parser.add_argument(
        "-c",
        "--dir",
        dest="directory",
        metavar="<dir>",
        help="Launch directory (default: current tmux pane path, else $PWD)",
    )
    parser.add_argument(
        "-e",
        "--effort",
        choices=_EFFORT_CHOICES,
        metavar="<level>",
        help=(
            "Explicit reasoning effort for this launch "
            f"({', '.join(_EFFORT_CHOICES)}); unsupported levels are a usage error"
        ),
    )
    parser.add_argument(
        "-j",
        "--json",
        action="store_true",
        help="Emit a versioned JSON envelope of the catalog or the dry-run plan",
    )
    parser.add_argument(
        "-l",
        "--list",
        action="store_true",
        help="Print the catalog as a table; works outside tmux (not a subcommand)",
    )
    parser.add_argument(
        "-n",
        "--dry-run",
        action="store_true",
        help="Print the window name, directory, env, and exact command; change nothing",
    )
    parser.add_argument(
        "-r",
        "--refresh",
        action="store_true",
        help="Rebuild the catalog cache before doing anything else",
    )
    parser.add_argument(
        "-s",
        "--safe",
        action="store_true",
        help="Launch without the provider's approval-bypass args",
    )
    parser.add_argument(
        "-v",
        "--verbose",
        action="store_true",
        help="With --list, add resolved paths, full commands, and install hints",
    )
    parser.add_argument(
        "--renumber",
        action="store_true",
        help=argparse.SUPPRESS,
    )


__all__ = ["register_tmux_agent_parser"]
