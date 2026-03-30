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


def register_commit_parser(subparsers: argparse._SubParsersAction) -> None:
    """Register the 'commit' subcommand parser."""
    commit_parser = subparsers.add_parser(
        "commit",
        help="Dispatch a VCS commit operation",
    )
    commit_subparsers = commit_parser.add_subparsers(
        dest="commit_subcommand", help="Commit subcommands"
    )

    def add_common_commit_args(parser: argparse.ArgumentParser) -> None:
        parser.add_argument(
            "-m",
            "--message",
            help="Commit message string",
        )
        parser.add_argument(
            "-F",
            "--message-file",
            help="Path to file containing the commit message / PR description",
        )
        parser.add_argument(
            "-p",
            "--project",
            help="Project name (e.g., sase-google) to commit to",
        )
        parser.add_argument(
            "-f",
            "--file",
            action="append",
            default=[],
            dest="files",
            help="File to stage (repeat for multiple; omit to stage all changes)",
        )
        parser.add_argument(
            "-n",
            "--name",
            help="Branch/CL name (required for create_pull_request)",
        )
        parser.add_argument(
            "-b",
            "--bead-id",
            help="Bead ID to close and associate with the commit",
        )
        parser.add_argument(
            "-c",
            "--checkout-target",
            default="HEAD~1",
            help="Branch point for create_pull_request (default: HEAD~1)",
        )
        parser.add_argument(
            "-M",
            "--method",
            choices=["create_commit", "create_proposal", "create_pull_request"],
            help="Override commit method (default: based on subcommand)",
        )

    # sase commit create
    create_parser = commit_subparsers.add_parser("create", help="Create a VCS commit")
    add_common_commit_args(create_parser)

    # sase commit proposal
    proposal_parser = commit_subparsers.add_parser(
        "proposal", help="Create a VCS proposal (e.g., proposed commit entry)"
    )
    add_common_commit_args(proposal_parser)

    # sase commit pull-request
    pr_parser = commit_subparsers.add_parser(
        "pull-request", help="Create a VCS pull request / changelist"
    )
    add_common_commit_args(pr_parser)


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
