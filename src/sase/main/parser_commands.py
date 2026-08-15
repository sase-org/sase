"""Argument parser definitions for misc CLI subcommands."""

import argparse


def register_comments_parser(subparsers: argparse._SubParsersAction) -> None:
    """Register the 'comments' subcommand parser."""
    comments_parser = subparsers.add_parser(
        "comments",
        help="Preview mentor comments from JSON (reads from stdin or file)",
    )
    comments_parser.add_argument(
        "file",
        nargs="?",
        help="Path to JSON file containing comments (default: read from stdin)",
    )
    comments_parser.add_argument(
        "-c",
        "--context",
        type=int,
        default=5,
        help="Lines of code context above/below the target line (default: 5)",
    )


def register_config_parser(subparsers: argparse._SubParsersAction) -> None:
    """Register the 'config' subcommand parser."""
    config_parser = subparsers.add_parser(
        "config",
        help="Inspect merged configuration, layers, and mentor profile matching",
    )
    config_subparsers = config_parser.add_subparsers(
        dest="config_subcommand", help="Config subcommands"
    )

    # sase config init
    config_init_parser = config_subparsers.add_parser(
        "init",
        help="Initialize the explicit SASE owner identity",
        description=(
            "Interactively create or migrate id.username and id.machine_name "
            "in the selected machine overlay, then record the local selector."
        ),
    )
    config_init_parser.add_argument(
        "-c",
        "--check",
        action="store_true",
        help="Report whether owner identity initialization or migration is needed",
    )

    # sase config layers
    config_subparsers.add_parser(
        "layers", help="Show per-layer breakdown of the config merge chain"
    )

    # sase config mentor-match
    config_mentor_match_parser = config_subparsers.add_parser(
        "mentor-match",
        help="Trace mentor profile matching for a Patch",
    )
    config_mentor_match_parser.add_argument(
        "changespec_name", help="NAME of the ChangeSpec to trace matching for"
    )

    # sase config show
    config_show_parser = config_subparsers.add_parser(
        "show", help="Print the final merged config as YAML"
    )
    config_show_parser.add_argument(
        "-k",
        "--key",
        help="Extract a specific top-level key (e.g., mentor_profiles)",
    )


def register_file_parser(subparsers: argparse._SubParsersAction) -> None:
    """Register the 'file' subcommand parser."""
    file_parser = subparsers.add_parser(
        "file",
        help="Filesystem completion helpers (consumed by editor integrations)",
    )
    file_subparsers = file_parser.add_subparsers(dest="file_subcommand")

    # sase file list
    list_parser = file_subparsers.add_parser(
        "list",
        help="List filesystem completion candidates as JSON",
    )
    list_parser.add_argument(
        "-p",
        "--path",
        default=".",
        help="Directory to anchor relative paths from (default: current dir)",
    )
    list_parser.add_argument(
        "-t",
        "--token",
        default="",
        help="Partial token under cursor (e.g., 'src/foo'); empty lists --path",
    )


def register_file_history_parser(subparsers: argparse._SubParsersAction) -> None:
    """Register the 'file-history' subcommand parser."""
    fh_parser = subparsers.add_parser(
        "file-history",
        help="Inspect and modify the file-reference history",
    )
    fh_subparsers = fh_parser.add_subparsers(dest="file_history_subcommand")

    # sase file-history list
    fh_subparsers.add_parser(
        "list",
        help="Print the recency-ordered file-reference history as a JSON array",
    )

    # sase file-history delete <path>
    fh_delete_parser = fh_subparsers.add_parser(
        "delete",
        help="Remove one entry from the file-reference history",
    )
    fh_delete_parser.add_argument(
        "-p",
        "--path",
        required=True,
        help="Path entry to remove (must exactly match the stored value)",
    )


def register_logs_parser(subparsers: argparse._SubParsersAction) -> None:
    """Register the 'logs' subcommand parser."""
    logs_parser = subparsers.add_parser(
        "logs",
        help="Collect logs and runtime data for a date range into a pack directory",
    )
    logs_parser.add_argument(
        "daterange",
        help="Date range to collect. Formats: YYmmdd, YYmmddHHMMSS, -Nd, 0d, "
        "START..END (e.g., -7d..0d, 260315..260318, -7d)",
    )


def register_revive_log_parser(subparsers: argparse._SubParsersAction) -> None:
    """Register the 'revive-log' subcommand parser."""
    revive_log_parser = subparsers.add_parser(
        "revive-log",
        help="Show recent agent revive attempts from ~/.sase/logs/events.jsonl",
    )
    revive_log_parser.add_argument(
        "--all",
        action="store_true",
        help="Show every record in events.jsonl (default: most recent 20)",
    )
    revive_log_parser.add_argument(
        "--limit",
        type=int,
        default=20,
        help="Maximum number of records to show (default: 20)",
    )
    revive_log_parser.add_argument(
        "--since",
        default=None,
        help="Only show records on/after this date (same grammar as 'sase logs')",
    )
    revive_log_parser.add_argument(
        "--outcome",
        choices=("success", "failure"),
        default=None,
        help="Filter by outcome",
    )
    output_group = revive_log_parser.add_mutually_exclusive_group()
    output_group.add_argument(
        "--json",
        dest="as_json",
        action="store_true",
        help="Emit one JSON object per line for machine consumption",
    )
    output_group.add_argument(
        "--jsonl",
        dest="as_json",
        action="store_true",
        help="Alias for --json",
    )


def register_lsp_parser(subparsers: argparse._SubParsersAction) -> None:
    """Register the 'lsp' subcommand parser."""
    lsp_parser = subparsers.add_parser(
        "lsp",
        help="Start the SASE xprompt language server",
        description=(
            "Start the SASE xprompt language server. Set SASE_XPROMPT_LSP_CMD "
            "to override the server command during development."
        ),
    )
    lsp_parser.add_argument(
        "-V",
        "--version",
        action="store_true",
        help="Print the xprompt LSP server version and exit",
    )
    lsp_parser.add_argument(
        "lsp_args",
        nargs=argparse.REMAINDER,
        help=argparse.SUPPRESS,
    )


def register_notify_parser(subparsers: argparse._SubParsersAction) -> None:
    """Register the 'notify' subcommand parser."""
    notify_parser = subparsers.add_parser(
        "notify",
        help="Create or inspect notifications",
        description=(
            "Create and inspect raw notifications. Privileged gate actions must be "
            "created with `sase gate create`. With no subcommand, delegates to "
            "`sase notify list`."
        ),
    )
    notify_parser.add_argument(
        "-s",
        "--sender",
        default=None,
        help="Notification sender name (overrides sender in JSON input)",
    )
    notify_parser.add_argument(
        "-t",
        "--tag",
        action="append",
        default=None,
        help="Tag for a created notification; repeat to add more tags",
    )
    notify_sub = notify_parser.add_subparsers(
        dest="notify_subcommand", help="Notification subcommands"
    )

    from sase.ops.commands.notify import add_notify_operation_parsers

    add_notify_operation_parsers(notify_sub)

    create_parser = notify_sub.add_parser(
        "create",
        help="Create a notification (reads JSON from stdin or uses flags)",
        description=(
            "Create a raw notification from stdin JSON. Raw notifications accept "
            "sender, icon, color, notes, files, tags, action, action_data, and "
            "silent. The color is an '#RRGGBB' accent for the notification-panel "
            "tab this row lands in. "
            "Privileged gate actions cannot be created through this raw notification "
            "interface; use `sase gate create` instead."
        ),
        epilog=(
            "examples:\n"
            '  printf \'%s\\n\' \'{"sender":"worker","icon":"✅",'
            '"notes":["Done"]}\' | sase notify create'
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    create_parser.add_argument(
        "-s",
        "--sender",
        default=None,
        help="Notification sender name (overrides sender in JSON input)",
    )
    create_parser.add_argument(
        "-t",
        "--tag",
        action="append",
        default=None,
        help="Tag for the created notification; repeat to add more tags",
    )

    list_parser = notify_sub.add_parser(
        "list",
        help="List recent notifications (pretty output by default, JSON with -j)",
    )
    list_parser.add_argument(
        "-a",
        "--all",
        action="store_true",
        help="Include dismissed notifications",
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
        help="Maximum number of notifications to return (default: 20)",
    )
    list_parser.add_argument(
        "-q",
        "--query",
        default=None,
        help="Case-insensitive substring filter over notification fields",
    )
    list_parser.add_argument(
        "-s",
        "--sender",
        default=None,
        help="Only include notifications from this sender",
    )
    list_parser.add_argument(
        "-t",
        "--tag",
        default=None,
        help="Only include notifications with this tag",
    )
    list_parser.add_argument(
        "-u",
        "--unread",
        action="store_true",
        help="Only include unread notifications",
    )
    show_parser = notify_sub.add_parser(
        "show",
        help="Show one notification by id",
    )
    show_parser.add_argument(
        "-f",
        "--format",
        choices=("markdown", "json"),
        default="markdown",
        help="Output format: 'markdown' (default) or 'json'",
    )
    show_parser.add_argument(
        "-i",
        "--id",
        required=True,
        help="Notification id to inspect",
    )


def register_path_parser(subparsers: argparse._SubParsersAction) -> None:
    """Register the 'path' subcommand parser."""
    path_parser = subparsers.add_parser(
        "path",
        help="Print well-known sase paths (for editor integration)",
    )
    path_parser.add_argument(
        "name",
        choices=[
            "config-schema",
            "xprompts-dir",
            "xprompts-schema",
            "xprompts-collection-schema",
        ],
        help="Which path to print",
    )


def register_questions_parser(subparsers: argparse._SubParsersAction) -> None:
    """Register the 'questions' subcommand parser."""
    questions_parser = subparsers.add_parser(
        "questions",
        help="Ask the user questions (used by /sase_questions skill)",
    )
    questions_parser.add_argument(
        "questions_json", help="JSON string containing questions"
    )


def register_run_parser(subparsers: argparse._SubParsersAction) -> None:
    """Register the 'run' subcommand parser."""
    run_parser = subparsers.add_parser(
        "run",
        usage="sase run [-h] [PROMPT]",
        help="Launch a detached background agent from a prompt or workflow",
        description=(
            "Launch a detached background coding-agent run from a prompt, "
            "xprompt, or workflow. Runs use the same launch machinery as ACE "
            "and appear in the ACE Agents tab."
        ),
        epilog=(
            "Examples:\n"
            '  sase run "#git:home summarize what this repository does; do not change files"\n'
            '  sase run "#fork(agent_name) follow up on the previous result"\n'
            "  sase chat list"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )

    run_parser.add_argument(
        "prompt",
        nargs="?",
        metavar="PROMPT",
        help="Prompt, xprompt reference, workflow reference, or '.' for prompt history.",
    )
