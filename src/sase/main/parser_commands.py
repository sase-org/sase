"""Argument parser definitions for misc CLI subcommands."""

import argparse


def register_agents_parser(subparsers: argparse._SubParsersAction) -> None:
    """Register the 'agents' subcommand parser."""
    agents_parser = subparsers.add_parser(
        "agents",
        help="Inspect, show, and kill running agents across all projects",
    )
    agents_sub = agents_parser.add_subparsers(
        dest="agents_subcommand", help="Agents subcommands"
    )

    # sase agents status (default when no subcommand given)
    status_parser = agents_sub.add_parser(
        "status",
        help="List running agents (pretty table by default, JSON with -j)",
    )
    status_parser.add_argument(
        "-a",
        "--all",
        action="store_true",
        help=(
            "Include recently-completed DONE/FAILED agents"
            " (capped at 50 most-recent per project)"
        ),
    )
    status_parser.add_argument(
        "-j",
        "--json",
        action="store_true",
        help="Emit a machine-readable JSON array (stable schema)",
    )
    status_parser.add_argument(
        "-p",
        "--project",
        help="Only show agents for the given project name",
    )

    # sase agents kill -n NAME
    kill_parser = agents_sub.add_parser(
        "kill",
        help="SIGTERM a running agent by name",
    )
    kill_parser.add_argument(
        "-n",
        "--name",
        required=True,
        help="Name of the agent to kill",
    )

    # sase agents show -n NAME
    show_parser = agents_sub.add_parser(
        "show",
        help="Render a full detail panel for one agent",
    )
    show_parser.add_argument(
        "-n",
        "--name",
        required=True,
        help="Name of the agent to show",
    )

    # sase agents tag {add,remove,list}
    tag_parser = agents_sub.add_parser(
        "tag",
        help="Manage user-defined tags on agents (used by the Agents tab)",
    )
    tag_sub = tag_parser.add_subparsers(dest="tag_subcommand", help="Tag subcommands")

    tag_add_parser = tag_sub.add_parser(
        "add",
        help="Add one or more tags to an agent",
    )
    tag_add_parser.add_argument(
        "-n",
        "--name",
        required=True,
        help="Name of the agent to tag",
    )
    tag_add_parser.add_argument(
        "-t",
        "--tag",
        action="append",
        dest="tags",
        required=True,
        help="Tag name (without '@'); repeat -t to add several at once",
    )

    tag_remove_parser = tag_sub.add_parser(
        "remove",
        help="Remove one or more tags from an agent",
    )
    tag_remove_parser.add_argument(
        "-n",
        "--name",
        required=True,
        help="Name of the agent to untag",
    )
    tag_remove_parser.add_argument(
        "-t",
        "--tag",
        action="append",
        dest="tags",
        required=True,
        help="Tag name (without '@'); repeat -t to remove several at once",
    )

    tag_list_parser = tag_sub.add_parser(
        "list",
        help="Print tags as JSON (all agents, or filtered by --name)",
    )
    tag_list_parser.add_argument(
        "-n",
        "--name",
        default=None,
        help="Limit output to a single agent",
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
        help="Dispatch a VCS commit operation",
    )
    msg_group = commit_parser.add_mutually_exclusive_group()
    msg_group.add_argument(
        "-m",
        "--message",
        help="Commit message string",
    )
    msg_group.add_argument(
        "-M",
        "--message-file",
        help="Path to file containing the commit message / PR description",
    )
    commit_parser.add_argument(
        "-f",
        "--file",
        action="append",
        default=[],
        dest="files",
        help="File to stage (repeat for multiple; omit to stage all changes)",
    )
    commit_parser.add_argument(
        "-n",
        "--name",
        help="Branch/CL name (required for create_pull_request)",
    )
    commit_parser.add_argument(
        "-b",
        "--bead-id",
        help="Bead ID to close and associate with the commit",
    )
    commit_parser.add_argument(
        "-B",
        "--bug-id",
        type=int,
        default=0,
        help="Bug ID to associate with the commit (overrides $SASE_BUG_ID)",
    )
    commit_parser.add_argument(
        "-c",
        "--checkout-target",
        default="HEAD~1",
        help="Branch point for create_pull_request (default: HEAD~1)",
    )
    commit_parser.add_argument(
        "-p",
        "--parent",
        help="Parent ChangeSpec name (overrides auto-detection from current branch)",
    )
    commit_parser.add_argument(
        "-s",
        "--status",
        type=str.lower,
        choices=["wip", "draft", "ready"],
        help="ChangeSpec status (overrides $SASE_PR_STATUS; default: draft)",
    )
    from sase.workflows.commit.workflow import METHOD_ALIASES, VALID_METHODS

    commit_parser.add_argument(
        "-t",
        "--type",
        dest="method",
        choices=[*VALID_METHODS, *METHOD_ALIASES],
        help="Commit method (default: $SASE_COMMIT_METHOD or create_commit)",
    )
    commit_parser.add_argument(
        "-r",
        "--resume",
        action="store_true",
        help=(
            "Resume a previously-checkpointed commit after manual conflict "
            "resolution. When set, -m/-M/-f and other commit args are ignored."
        ),
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


def register_init_skills_parser(subparsers: argparse._SubParsersAction) -> None:
    """Register the 'init-skills' subcommand parser."""
    init_skills_parser = subparsers.add_parser(
        "init-skills",
        help="Generate and deploy agent skill files from xprompt sources",
    )
    init_skills_parser.add_argument(
        "-A",
        "--no-apply",
        action="store_true",
        help="With use_chezmoi: skip running 'chezmoi apply' after pushing",
    )
    init_skills_parser.add_argument(
        "-C",
        "--no-commit",
        action="store_true",
        help="With use_chezmoi: skip the entire git commit/push/apply sequence",
    )
    init_skills_parser.add_argument(
        "-f",
        "--force",
        action="store_true",
        help="Overwrite existing files without confirmation",
    )
    init_skills_parser.add_argument(
        "-n",
        "--dry-run",
        action="store_true",
        help="Show what would be written without writing",
    )
    init_skills_parser.add_argument(
        "-P",
        "--no-push",
        action="store_true",
        help="With use_chezmoi: commit but skip 'git pull --rebase && git push' and 'chezmoi apply'",
    )
    init_skills_parser.add_argument(
        "-p",
        "--provider",
        choices=["claude", "gemini", "codex"],
        help="Only deploy for a specific provider (default: all)",
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


def register_telemetry_parser(subparsers: argparse._SubParsersAction) -> None:
    """Register the 'telemetry' subcommand parser."""
    telemetry_parser = subparsers.add_parser(
        "telemetry",
        help="Inspect and monitor Prometheus telemetry metrics",
    )
    tel_subparsers = telemetry_parser.add_subparsers(
        dest="telemetry_subcommand", help="Telemetry subcommands"
    )

    # sase telemetry dashboard
    dashboard_parser = tel_subparsers.add_parser(
        "dashboard", help="Live auto-refreshing TUI dashboard"
    )
    dashboard_parser.add_argument(
        "-i",
        "--interval",
        type=int,
        default=5,
        help="Refresh interval in seconds (default: 5)",
    )
    dashboard_parser.add_argument(
        "-S",
        "--source",
        choices=["auto", "pushgateway", "exposition"],
        default="auto",
        help="Data source (default: auto)",
    )
    dashboard_parser.add_argument(
        "-c",
        "--charts",
        action="store_true",
        help="Enable charts mode with historical data from Prometheus",
    )
    dashboard_parser.add_argument(
        "-r",
        "--range",
        choices=["1h", "6h", "24h", "7d"],
        default="1h",
        help="Time range for charts mode (default: 1h)",
    )
    dashboard_parser.add_argument(
        "-s",
        "--subsystem",
        help="Focus on a single subsystem (larger charts, more detail)",
    )

    # sase telemetry export-config
    export_config_parser = tel_subparsers.add_parser(
        "export-config",
        help="Export bundled monitoring config (Prometheus + Grafana + Docker Compose)",
    )
    export_config_parser.add_argument(
        "-o",
        "--output-dir",
        default="./sase-monitoring",
        help="Target directory (default: ./sase-monitoring/)",
    )
    export_config_parser.add_argument(
        "-f",
        "--force",
        action="store_true",
        help="Overwrite the target directory if it already exists",
    )

    # sase telemetry health
    health_parser = tel_subparsers.add_parser(
        "health", help="Traffic-light health assessment"
    )
    health_parser.add_argument(
        "-j",
        "--json",
        action="store_true",
        help="Machine-readable JSON output",
    )
    health_parser.add_argument(
        "-S",
        "--source",
        choices=["auto", "pushgateway", "exposition"],
        default="auto",
        help="Data source (default: auto)",
    )

    # sase telemetry list
    list_parser = tel_subparsers.add_parser(
        "list", help="Show the metric catalog from internal definitions"
    )
    list_parser.add_argument(
        "-s",
        "--subsystem",
        help="Filter to a specific subsystem (e.g., 'Agent Lifecycle')",
    )
    list_parser.add_argument(
        "-t",
        "--type",
        choices=["counter", "gauge", "histogram"],
        help="Filter by metric type",
    )

    # sase telemetry snapshot
    snapshot_parser = tel_subparsers.add_parser(
        "snapshot", help="Fetch and display current metric values"
    )
    snapshot_parser.add_argument(
        "-S",
        "--source",
        choices=["auto", "pushgateway", "exposition"],
        default="auto",
        help="Where to fetch metrics from (default: auto)",
    )
    snapshot_parser.add_argument(
        "-f",
        "--format",
        choices=["rich", "json", "prometheus"],
        default="rich",
        help="Output format (default: rich)",
    )
    snapshot_parser.add_argument(
        "-s",
        "--subsystem",
        help="Filter by subsystem",
    )

    # sase telemetry status
    tel_subparsers.add_parser("status", help="Quick health check and config display")


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

    # xprompt catalog
    catalog_parser = xprompt_subparsers.add_parser(
        "catalog",
        help="Render every visible xprompt to a beautifully-formatted PDF",
    )
    catalog_parser.add_argument(
        "-o",
        "--out",
        dest="out_dir",
        default=None,
        help="Directory to write the PDF (defaults to a tempdir).",
    )
