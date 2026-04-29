"""Argument parser definitions for misc CLI subcommands."""

import argparse


def register_changespec_parser(subparsers: argparse._SubParsersAction) -> None:
    """Register the 'changespec' subcommand parser."""
    cs_parser = subparsers.add_parser(
        "changespec",
        help="ChangeSpec maintenance commands (DELTAS sync, etc.)",
    )
    cs_subparsers = cs_parser.add_subparsers(
        dest="changespec_subcommand", help="ChangeSpec subcommands"
    )

    # sase changespec current [-f FORMAT] [-p <project_file>]
    current_parser = cs_subparsers.add_parser(
        "current",
        help="Show the ChangeSpec associated with the current VCS checkout",
    )
    current_parser.add_argument(
        "-f",
        "--format",
        choices=["markdown", "plain", "json"],
        default="markdown",
        help="Output format (default: markdown)",
    )
    current_parser.add_argument(
        "-p",
        "--project-file",
        dest="project_file",
        default=None,
        help="Path to the project .gp file (default: inferred from current workspace)",
    )

    # sase changespec sync-deltas -c <cl_name> [-p <project_file>]
    sync_deltas_parser = cs_subparsers.add_parser(
        "sync-deltas",
        help="Recompute the DELTAS field for a ChangeSpec from the live VCS state",
    )
    sync_deltas_parser.add_argument(
        "-c",
        "--cl",
        dest="cl_name",
        required=True,
        help="NAME of the ChangeSpec whose DELTAS should be recomputed",
    )
    sync_deltas_parser.add_argument(
        "-p",
        "--project-file",
        dest="project_file",
        default=None,
        help="Path to the project .gp file (default: inferred from current workspace)",
    )
    sync_deltas_parser.add_argument(
        "-w",
        "--workspace-dir",
        dest="workspace_dir",
        default=None,
        help="VCS workspace directory to query (default: current directory)",
    )


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

    # sase config layers
    config_subparsers.add_parser(
        "layers", help="Show per-layer breakdown of the config merge chain"
    )

    # sase config mentor-match
    config_mentor_match_parser = config_subparsers.add_parser(
        "mentor-match",
        help="Trace mentor profile matching for a ChangeSpec",
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


def register_notify_parser(subparsers: argparse._SubParsersAction) -> None:
    """Register the 'notify' subcommand parser."""
    notify_parser = subparsers.add_parser(
        "notify",
        help="Create a notification (reads JSON from stdin or uses flags)",
    )
    notify_parser.add_argument(
        "-s",
        "--sender",
        default=None,
        help="Notification sender name (overrides sender in JSON input)",
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


def register_plan_parser(subparsers: argparse._SubParsersAction) -> None:
    """Register the 'plan' subcommand parser."""
    plan_parser = subparsers.add_parser(
        "plan",
        help="Submit a plan file for approval (used by /sase_plan skill)",
    )
    plan_parser.add_argument("plan_file", help="Path to the plan .md file")


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
        help="Run a workflow or execute a query directly (e.g., 'sase run \"Your question here\"')",
    )

    # Options for 'run' (keep sorted alphabetically by long option name)
    run_parser.add_argument(
        "-d",
        "--daemon",
        action="store_true",
        help="Run prompt as a detached background agent (appears in TUI Agents tab)",
    )
    run_parser.add_argument(
        "-l",
        "--list",
        action="store_true",
        help="List all available chat history files",
    )
    run_parser.add_argument(
        "-r",
        "--resume",
        dest="continue_history",
        nargs="?",
        const="",  # Empty string means "use most recent"
        help="Resume a previous conversation. Optionally specify history file basename or path (defaults to most recent).",
    )


def register_search_parser(subparsers: argparse._SubParsersAction) -> None:
    """Register the 'search' subcommand parser."""
    search_parser = subparsers.add_parser(
        "search",
        help="Search for ChangeSpecs matching a query and display them",
    )
    search_parser.add_argument(
        "query",
        help="Query string for filtering ChangeSpecs. "
        "Examples: '\"feature\" AND \"Ready\"', '+myproject', '!!! OR @@@'",
    )
    # Options for 'search' (keep sorted alphabetically by long option name)
    search_parser.add_argument(
        "-f",
        "--format",
        choices=["plain", "rich", "markdown"],
        default="rich",
        help="Output format: 'plain' for simple text, 'rich' for styled panels, "
        "'markdown' for agent-friendly markdown (default: rich)",
    )
