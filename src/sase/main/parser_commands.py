"""Argument parser definitions for misc CLI subcommands."""

import argparse


def register_amend_parser(subparsers: argparse._SubParsersAction) -> None:
    """Register the 'amend' subcommand parser."""
    amend_parser = subparsers.add_parser(
        "amend",
        help="Amend the current commit with COMMITS tracking",
    )
    amend_parser.add_argument(
        "note",
        nargs="*",
        help='The note for this amend (e.g., "Fixed typo in README"). '
        "When using --accept, this should be proposal entries instead.",
    )
    # Options for 'amend' (keep sorted alphabetically by long option name)
    amend_parser.add_argument(
        "-a",
        "--accept",
        action="store_true",
        help="Accept one or more proposed COMMITS entries by applying their diffs. "
        "When used, positional args are proposal entries (format: <id>[(<msg>)]). "
        "Examples: '2a', '2b(Add foobar field)'.",
    )
    amend_parser.add_argument(
        "-c",
        "--chat",
        dest="chat_path",
        help="Path to the chat file associated with this amend.",
    )
    amend_parser.add_argument(
        "-C",
        "--cl",
        dest="cl_name",
        help="CL name (defaults to current branch name). Only used with --accept.",
    )
    amend_parser.add_argument(
        "-p",
        "--propose",
        action="store_true",
        help="Create a proposed COMMITS entry instead of amending. "
        "Saves the diff, adds a proposed entry (e.g., 2a), and cleans workspace.",
    )
    amend_parser.add_argument(
        "-t",
        "--target-dir",
        dest="target_dir",
        help="Directory to run commands in (default: current directory).",
    )
    amend_parser.add_argument(
        "-T",
        "--timestamp",
        help="Shared timestamp for synced chat/diff files (YYmmdd_HHMMSS format).",
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


def register_commit_parser(subparsers: argparse._SubParsersAction) -> None:
    """Register the 'commit' subcommand parser."""
    commit_parser = subparsers.add_parser(
        "commit",
        help="Create a commit with formatted CL description and metadata",
    )
    commit_parser.add_argument(
        "cl_name",
        help="CL name to use for the commit (e.g., 'baz_feature'). The project name "
        "will be automatically prepended if not already present.",
    )
    commit_parser.add_argument(
        "file_path",
        nargs="?",
        help="Path to the file containing the CL description. "
        "If not provided, vim will be opened to write the commit message.",
    )
    # Options for 'commit' (keep sorted alphabetically by long option name)
    # Bug options are mutually exclusive - use either BUG= or FIXED= tag
    bug_group = commit_parser.add_mutually_exclusive_group()
    bug_group.add_argument(
        "-b",
        "--bug",
        help="Bug number for BUG= tag. Defaults to the VCS provider's bug detection.",
    )
    bug_group.add_argument(
        "-B",
        "--fixed-bug",
        help="Bug number for FIXED= tag (bug is fixed by this CL).",
    )
    commit_parser.add_argument(
        "-c",
        "--chat",
        dest="chat_path",
        help="Path to the chat file associated with this commit (for COMMITS entry).",
    )
    commit_parser.add_argument(
        "-m",
        "--message",
        help="Commit message to use directly (mutually exclusive with file_path).",
    )
    commit_parser.add_argument(
        "-n",
        "--note",
        help="Custom note for the initial COMMITS entry (default: 'Initial Commit').",
    )
    commit_parser.add_argument(
        "-p",
        "--project",
        help="Project name to prepend to the CL description. Defaults to output of 'sase_workspace_name'.",
    )
    commit_parser.add_argument(
        "-t",
        "--timestamp",
        help="Shared timestamp for synced chat/diff files (YYmmdd_HHMMSS format).",
    )
    commit_parser.add_argument(
        "-e",
        "--end-timestamp",
        dest="end_timestamp",
        help="End timestamp for duration calculation (YYmmdd_HHMMSS format).",
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

    # sase config show
    config_show_parser = config_subparsers.add_parser(
        "show", help="Print the final merged config as YAML"
    )
    config_show_parser.add_argument(
        "-k",
        "--key",
        help="Extract a specific top-level key (e.g., mentor_profiles)",
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


def register_init_git_parser(subparsers: argparse._SubParsersAction) -> None:
    """Register the 'init-git' subcommand parser."""
    init_git_parser = subparsers.add_parser(
        "init-git",
        help="Initialize a new bare-repo-backed git project",
    )
    init_git_parser.add_argument(
        "project_name",
        help="Name of the project to initialize",
    )
    # Options for 'init-git' (keep sorted alphabetically by long option name)
    init_git_parser.add_argument(
        "-b",
        "--bare-dir",
        default=None,
        help="Override bare repo path (default: ~/.sase/repos/<name>.git)",
    )
    init_git_parser.add_argument(
        "-c",
        "--clone-dir",
        default=None,
        help="Override clone path (default: ~/projects/git/<name>/)",
    )
    init_git_parser.add_argument(
        "-e",
        "--existing",
        default=None,
        help="Path to an existing bare repo to register instead of creating new",
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


def register_restore_parser(subparsers: argparse._SubParsersAction) -> None:
    """Register the 'restore' subcommand parser."""
    restore_parser = subparsers.add_parser(
        "restore",
        help="Restore a reverted ChangeSpec by re-applying its diff and creating a new CL",
    )
    restore_parser.add_argument(
        "name",
        nargs="?",
        help="NAME of the reverted ChangeSpec to restore (e.g., 'foobar_feature__2')",
    )
    # Options for 'restore' (keep sorted alphabetically by long option name)
    restore_parser.add_argument(
        "-l",
        "--list",
        action="store_true",
        help="List all reverted ChangeSpecs",
    )


def register_revert_parser(subparsers: argparse._SubParsersAction) -> None:
    """Register the 'revert' subcommand parser."""
    revert_parser = subparsers.add_parser(
        "revert",
        help="Revert a ChangeSpec by pruning its CL and archiving the diff",
    )
    revert_parser.add_argument(
        "name",
        help="NAME of the ChangeSpec to revert",
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
        choices=["plain", "rich"],
        default="rich",
        help="Output format: 'plain' for simple text, 'rich' for styled panels (default: rich)",
    )


def register_xprompt_parser(subparsers: argparse._SubParsersAction) -> None:
    """Register the 'xprompt' subcommand parser."""
    xprompt_parser = subparsers.add_parser(
        "xprompt",
        help="Expand and visualize xprompt workflows",
    )
    xprompt_subparsers = xprompt_parser.add_subparsers(dest="xprompt_subcommand")

    # xprompt expand
    expand_parser = xprompt_subparsers.add_parser(
        "expand",
        help="Expand sase references (snippets, file refs) in a prompt",
    )
    expand_parser.add_argument(
        "prompt",
        nargs="?",
        help="Prompt text to expand. If not provided, reads from STDIN.",
    )
    expand_parser.add_argument(
        "-t",
        "--trace",
        action="store_true",
        help="Print expansion trace to stderr showing each resolved reference.",
    )

    # xprompt graph
    graph_parser = xprompt_subparsers.add_parser(
        "graph",
        help="Generate a DAG visualization of a workflow",
    )
    graph_parser.add_argument(
        "workflow_name",
        nargs="?",
        help="Workflow name to graph. If not provided, lists all workflows.",
    )
    graph_parser.add_argument(
        "-f",
        "--format",
        choices=["mermaid", "text"],
        default="mermaid",
        help="Output format (default: mermaid)",
    )

    # xprompt list
    xprompt_subparsers.add_parser(
        "list",
        help="List all available xprompts and workflows as JSON",
    )

    # xprompt explain
    explain_parser = xprompt_subparsers.add_parser(
        "explain",
        help="Dry-run: show execution plan without running anything",
    )
    explain_parser.add_argument(
        "workflow_name",
        help="Workflow name to explain.",
    )
    explain_parser.add_argument(
        "args",
        nargs="*",
        help="Positional arguments for the workflow.",
    )
    explain_parser.add_argument(
        "-a",
        "--arg",
        action="append",
        dest="named_args",
        metavar="KEY=VALUE",
        help="Named argument (can be repeated).",
    )
