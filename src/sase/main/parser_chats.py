"""Argument parser definition for the 'chats' CLI subcommand."""

import argparse


def register_chats_parser(subparsers: argparse._SubParsersAction) -> None:
    """Register the 'chats' subcommand parser."""
    chats_parser = subparsers.add_parser(
        "chats",
        help="Discover and inspect prior agent chat transcripts",
    )
    chats_sub = chats_parser.add_subparsers(
        dest="chats_subcommand", help="Chats subcommands"
    )

    # sase chats list
    list_parser = chats_sub.add_parser(
        "list",
        help="List recent chat transcripts (pretty table by default, JSON with -j)",
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
        help="Maximum number of transcripts to return (default: 20)",
    )
    list_parser.add_argument(
        "-q",
        "--query",
        default=None,
        help="Case-insensitive substring filter over path/basename/content",
    )

    # sase chats show
    show_parser = chats_sub.add_parser(
        "show",
        help="Show a chat transcript by agent name, path, or basename",
    )
    selector_group = show_parser.add_mutually_exclusive_group(required=True)
    selector_group.add_argument(
        "-n",
        "--agent",
        default=None,
        help="Resolve transcript by named agent (done.response_path or meta.chat_path)",
    )
    selector_group.add_argument(
        "-p",
        "--path",
        default=None,
        help="Path to a chat transcript file (~ is expanded)",
    )
    selector_group.add_argument(
        "-b",
        "--basename",
        default=None,
        help="Chat transcript basename (with or without .md extension)",
    )
    show_parser.add_argument(
        "-f",
        "--format",
        choices=("raw", "resume", "response"),
        default="raw",
        help=(
            "Output format: 'raw' (default) prints transcript markdown,"
            " 'resume' prints flattened User/Assistant turns,"
            " 'response' prints the latest response only"
        ),
    )
