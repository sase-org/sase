"""Argument parser definition for the 'prompt' CLI subcommand."""

import argparse


def register_prompt_parser(subparsers: argparse._SubParsersAction) -> None:
    """Register the 'prompt' subcommand parser and its subcommands."""
    prompt_parser = subparsers.add_parser(
        "prompt",
        help="Inspect, search, and reuse previously submitted agent prompts",
    )
    prompt_sub = prompt_parser.add_subparsers(
        dest="prompt_subcommand", help="Prompt subcommands"
    )

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
