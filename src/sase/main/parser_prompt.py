"""Argument parser definition for the 'prompt' CLI subcommand."""

import argparse


def _add_prefix_option(parser: argparse.ArgumentParser) -> None:
    """Add the shared ``-P/--prefix`` VCS-tag replacement option."""
    parser.add_argument(
        "-P",
        "--prefix",
        default=None,
        metavar="VCS_PREFIX",
        help=(
            "Replace embedded VCS workflow tags with VCS_PREFIX before replay,"
            " e.g. reuse a '#gh:sase' prompt under '#gh:bob-cli'"
        ),
    )


def register_prompt_parser(subparsers: argparse._SubParsersAction) -> None:
    """Register the 'prompt' subcommand parser and its subcommands."""
    prompt_parser = subparsers.add_parser(
        "prompt",
        help="Inspect, search, and reuse previously submitted agent prompts",
    )
    prompt_sub = prompt_parser.add_subparsers(
        dest="prompt_subcommand", help="Prompt subcommands"
    )

    # sase prompt copy
    copy_parser = prompt_sub.add_parser(
        "copy",
        help="Copy a prompt's exact text to the system clipboard",
    )
    copy_parser.add_argument(
        "id",
        help="Prompt selector: ph_<prefix>, a bare hash prefix, or sha256:<hash>",
    )

    # sase prompt edit
    edit_parser = prompt_sub.add_parser(
        "edit",
        help="Open a prompt in the editor, then launch the edited text",
    )
    edit_parser.add_argument(
        "id",
        help="Prompt selector: ph_<prefix>, a bare hash prefix, or sha256:<hash>",
    )
    edit_parser.add_argument(
        "-d",
        "--daemon",
        action="store_true",
        help="Launch the edited prompt as a detached background agent",
    )
    _add_prefix_option(edit_parser)

    # sase prompt list
    list_parser = prompt_sub.add_parser(
        "list",
        help="List recent prompts (pretty table by default, JSON with -j)",
    )
    list_parser.add_argument(
        "-a",
        "--all",
        action="store_true",
        help="Include cancelled prompts alongside launched prompts",
    )
    list_parser.add_argument(
        "-c",
        "--cancelled",
        action="store_true",
        help="Show only cancelled prompts (takes precedence over --all)",
    )
    list_parser.add_argument(
        "-j",
        "--json",
        action="store_true",
        help="Emit a machine-readable JSON array (stable schema)",
    )
    list_parser.add_argument(
        "-l",
        "--limit",
        type=int,
        default=20,
        help="Maximum number of prompts to return (default: 20)",
    )
    list_parser.add_argument(
        "-q",
        "--query",
        default=None,
        help="Case-insensitive substring filter over exact prompt text",
    )

    # sase prompt run
    run_parser = prompt_sub.add_parser(
        "run",
        help="Launch a stored prompt by selector",
    )
    run_parser.add_argument(
        "id",
        help="Prompt selector: ph_<prefix>, a bare hash prefix, or sha256:<hash>",
    )
    run_parser.add_argument(
        "-d",
        "--daemon",
        action="store_true",
        help="Launch the prompt as a detached background agent",
    )
    run_parser.add_argument(
        "-e",
        "--edit",
        action="store_true",
        help="Open the prompt in the editor before launching",
    )
    _add_prefix_option(run_parser)

    # sase prompt select
    select_parser = prompt_sub.add_parser(
        "select",
        help="Pick a prompt with an fzf picker, then launch it",
    )
    select_parser.add_argument(
        "-a",
        "--all",
        action="store_true",
        help="Include cancelled prompts alongside launched prompts",
    )
    select_parser.add_argument(
        "-c",
        "--cancelled",
        action="store_true",
        help="Show only cancelled prompts (takes precedence over --all)",
    )
    select_parser.add_argument(
        "-d",
        "--daemon",
        action="store_true",
        help="Launch the selected prompt as a detached background agent",
    )
    select_parser.add_argument(
        "-e",
        "--edit",
        action="store_true",
        help="Open the selected prompt in the editor before launching",
    )
    _add_prefix_option(select_parser)
    select_parser.add_argument(
        "-q",
        "--query",
        default=None,
        help="Case-insensitive substring filter over candidates before fzf",
    )

    # sase prompt show
    show_parser = prompt_sub.add_parser(
        "show",
        help="Print a prompt by ID, hash prefix, or sha256:<hash>",
    )
    show_parser.add_argument(
        "id",
        help="Prompt selector: ph_<prefix>, a bare hash prefix, or sha256:<hash>",
    )
    show_parser.add_argument(
        "-f",
        "--format",
        choices=("raw", "markdown", "json"),
        default="raw",
        help=(
            "Output format: 'raw' (default) prints exact prompt text,"
            " 'markdown' prints a metadata header plus the body,"
            " 'json' prints metadata plus full text"
        ),
    )

    # sase prompt stats
    stats_parser = prompt_sub.add_parser(
        "stats",
        help="Summarize the prompt-history store (pretty by default, JSON with -j)",
    )
    stats_parser.add_argument(
        "-j",
        "--json",
        action="store_true",
        help="Emit a machine-readable JSON object (stable schema)",
    )
