"""Argument parser definition for the ``sase completion`` CLI subcommand."""

from __future__ import annotations

import argparse


def register_completion_parser(subparsers: argparse._SubParsersAction) -> None:
    """Register the ``sase completion`` command group."""
    completion_parser = subparsers.add_parser(
        "completion",
        help="Generate and inspect shell completion for the sase CLI",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        description=(
            "Generate native shell-completion scripts from the live sase "
            "argparse tree, and inspect the structural spec those scripts "
            "are built from.\n"
            "\n"
            "With no subcommand, `sase completion` defaults to "
            "`sase completion list`.\n"
            "\n"
            "Write generated scripts to a file. Do not "
            '`eval "$(sase completion zsh)"` — that would pay a full sase '
            "startup on every new shell."
        ),
        epilog=(
            "examples:\n"
            "  sase completion                         # same as list\n"
            "  sase completion list                    # shells and generator status\n"
            "  sase completion spec                    # structural JSON\n"
            "  sase completion spec -j -o spec.json    # write the snapshot artifact\n"
            "  sase completion zsh                     # print a compsys script\n"
            "  sase completion zsh -o ~/.zfunc/_sase   # write `_sase` for fpath"
        ),
    )
    completion_sub = completion_parser.add_subparsers(
        dest="completion_subcommand",
        help="Completion subcommands",
        metavar="{list,spec,zsh}",
    )

    _register_list_parser(completion_sub)
    _register_spec_parser(completion_sub)
    _register_zsh_parser(completion_sub)


def _register_list_parser(subparsers: argparse._SubParsersAction) -> None:
    list_parser = subparsers.add_parser(
        "list",
        help="Show which shells have a generator and their install status",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        description=(
            "List every supported shell, whether sase can generate a "
            "completion script for it, and the current install status. "
            "This phase reports generator availability; install later "
            "fills in path, `.zwc` freshness, and stamp version."
        ),
        epilog=("examples:\n  sase completion list\n  sase completion list --json"),
    )
    list_parser.add_argument(
        "-j",
        "--json",
        action="store_true",
        help="Emit machine-readable JSON",
    )


def _register_spec_parser(subparsers: argparse._SubParsersAction) -> None:
    spec_parser = subparsers.add_parser(
        "spec",
        help="Print the structural completion spec as JSON",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        description=(
            "Print the structural completion spec — the same JSON artifact "
            "the checked-in snapshot gate compares against. Descriptions "
            "are replaced by per-command digests so wording churn is a "
            "one-line diff. Use this as a stable integration point for "
            "other tools."
        ),
        epilog=(
            "examples:\n"
            "  sase completion spec\n"
            "  sase completion spec --json\n"
            "  sase completion spec -o cli_spec.json"
        ),
    )
    spec_parser.add_argument(
        "-j",
        "--json",
        action="store_true",
        help="Emit machine-readable JSON",
    )
    spec_parser.add_argument(
        "-o",
        "--output",
        metavar="FILE",
        default=None,
        help="Write the spec to FILE instead of stdout",
    )


def _register_zsh_parser(subparsers: argparse._SubParsersAction) -> None:
    zsh_parser = subparsers.add_parser(
        "zsh",
        help="Emit a native zsh compsys completion script",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        description=(
            "Print a `#compdef sase` compsys script with `_arguments -C "
            "-s -S`, option descriptions, exclusion lists, mutex groups, "
            "and remainder handling. Place the file on `fpath` as `_sase` "
            "before `compinit` and `zcompile` it. Do not eval the output."
        ),
        epilog=(
            "examples:\n  sase completion zsh\n  sase completion zsh -o ~/.zfunc/_sase"
        ),
    )
    zsh_parser.add_argument(
        "-o",
        "--output",
        metavar="FILE",
        default=None,
        help="Write the script to FILE instead of stdout",
    )


__all__ = ["register_completion_parser"]
