"""Argument parser definition for the 'chat' CLI subcommand."""

import argparse


def register_chat_parser(subparsers: argparse._SubParsersAction) -> None:
    """Register the 'chat' subcommand parser."""
    chat_parser = subparsers.add_parser(
        "chat",
        help="Discover and inspect prior agent chat transcripts",
    )
    chat_sub = chat_parser.add_subparsers(
        dest="chat_subcommand", help="Chat subcommands"
    )

    # sase chat list
    list_parser = chat_sub.add_parser(
        "list",
        help="List recent chat transcripts (pretty table by default, JSON with -j)",
        description=(
            "List recent chat transcripts, newest first, with the sync"
            " provenance of each one: 'local' (written here, not published),"
            " 'shared' (written here and published to an agents sidecar),"
            " 'remote' (imported from another machine), or 'unknown'"
            " (provenance could not be determined)."
        ),
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
        "-m",
        "--machine",
        default=None,
        help=(
            "Only show transcripts whose source machine matches this name"
            " (case-insensitive); remote transcripts report their origin"
            " machine, local and shared ones report this machine"
        ),
    )
    list_parser.add_argument(
        "-P",
        "--provenance",
        choices=("local", "shared", "remote", "unknown"),
        default=None,
        help="Only show transcripts with this sync provenance",
    )
    list_parser.add_argument(
        "-q",
        "--query",
        default=None,
        help="Case-insensitive substring filter over path/basename/content",
    )

    # sase chat show
    show_parser = chat_sub.add_parser(
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
