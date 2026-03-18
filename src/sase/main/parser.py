"""Argument parser creation for the SASE CLI tool."""

import argparse

from sase.ace.saved_queries import load_first_saved_query, load_last_query


def create_parser() -> argparse.ArgumentParser:
    """Create the argument parser with subcommands."""
    parser = argparse.ArgumentParser(
        description="SASE - Structured Agentic Software Engineering", prog="sase"
    )

    # Top-level subparsers
    top_level_subparsers = parser.add_subparsers(
        dest="command", help="Available commands", required=True
    )

    # =========================================================================
    # TOP-LEVEL SUBCOMMANDS (keep sorted alphabetically)
    # =========================================================================

    # --- ace ---
    ace_parser = top_level_subparsers.add_parser(
        "ace",
        help="Interactively navigate through ChangeSpecs matching a query",
    )
    # Optional positional argument with default
    ace_parser.add_argument(
        "query",
        nargs="?",
        default=load_last_query() or load_first_saved_query() or "!!!",
        help="Query string for filtering ChangeSpecs (default: first saved query, "
        "or '!!!' for error suffixes). "
        'Examples: \'"feature" AND "Ready"\', \'"myproject" OR "bugfix"\', '
        "'!!! AND @myproject'",
    )
    # Options for 'ace' (keep sorted alphabetically by long option name)
    ace_parser.add_argument(
        "-m",
        "--model-tier",
        choices=["large", "small"],
        default=None,
        help="Override model tier for ALL LLM provider instances (large or small)",
    )
    ace_parser.add_argument(
        "--model-size",
        choices=["big", "little"],
        default=None,
        help="Deprecated: use --model-tier instead",
    )
    ace_parser.add_argument(
        "-r",
        "--refresh-interval",
        type=int,
        default=10,
        help="Auto-refresh interval in seconds (default: 10, 0 to disable)",
    )
    ace_parser.add_argument(
        "--agent",
        action="store_true",
        help="Run in headless agent mode (returns JSON to stdout)",
    )
    ace_parser.add_argument(
        "--keys",
        nargs="*",
        help="Key names to press in agent mode (e.g., j j Enter)",
    )
    ace_parser.add_argument(
        "--size",
        default="120x40",
        help="Terminal size as WIDTHxHEIGHT for agent mode (default: 120x40)",
    )
    ace_parser.add_argument(
        "--no-axe",
        action="store_true",
        help="Disable auto-starting the axe daemon on startup",
    )
    ace_parser.add_argument(
        "--vcs-provider",
        choices=["git", "hg", "auto"],
        default=None,
        help="Override VCS provider ('git', 'hg', or 'auto' for auto-detection)",
    )

    # --- axe ---
    axe_parser = top_level_subparsers.add_parser(
        "axe",
        help="Schedule-based daemon for continuous ChangeSpec status updates",
    )
    # Only --vcs-provider lives on the root axe parser (applies globally)
    axe_parser.add_argument(
        "--vcs-provider",
        choices=["git", "hg", "auto"],
        default=None,
        help="Override VCS provider ('git', 'hg', or 'auto' for auto-detection)",
    )

    # Nested subparsers for axe
    axe_subparsers = axe_parser.add_subparsers(
        dest="axe_subcommand", help="Axe subcommands"
    )

    # --- axe start ---
    axe_start_parser = axe_subparsers.add_parser(
        "start", help="Start the axe orchestrator (spawns all lumberjacks)"
    )
    axe_start_parser.add_argument(
        "--max-hook-runners",
        type=int,
        default=None,
        help="Maximum concurrent hook runners (default: 3)",
    )
    axe_start_parser.add_argument(
        "--max-agent-runners",
        type=int,
        default=None,
        help="Maximum concurrent agent runners (default: 3)",
    )
    axe_start_parser.add_argument(
        "-q",
        "--query",
        default="",
        help="Query string for filtering ChangeSpecs (empty = all ChangeSpecs). "
        "Examples: '\"feature\" AND %%d', '+myproject', '!!! OR @@@'",
    )
    axe_start_parser.add_argument(
        "--zombie-timeout",
        type=int,
        default=None,
        help="Zombie detection timeout in seconds (default: 7200 = 2 hours). "
        "Hooks and CRS workflows running longer than this are marked as ZOMBIE.",
    )

    # --- axe stop ---
    axe_subparsers.add_parser("stop", help="Stop the running axe orchestrator")

    # --- axe chop ---
    axe_chop_parser = axe_subparsers.add_parser("chop", help="Chop management commands")
    axe_chop_subparsers = axe_chop_parser.add_subparsers(
        dest="axe_chop_subcommand", help="Chop subcommands"
    )

    # sase axe chop list
    axe_chop_subparsers.add_parser("list", help="List all registered chops")

    # sase axe chop run <name>
    axe_chop_run_parser = axe_chop_subparsers.add_parser(
        "run", help="Run a single chop once in the foreground"
    )
    axe_chop_run_parser.add_argument("chop_name", help="Name of the chop to run")

    # --- axe lumberjack ---
    axe_lumberjack_parser = axe_subparsers.add_parser(
        "lumberjack", help="Lumberjack management commands"
    )
    axe_lumberjack_subparsers = axe_lumberjack_parser.add_subparsers(
        dest="axe_lumberjack_subcommand", help="Lumberjack subcommands"
    )

    # sase axe lumberjack list
    axe_lumberjack_subparsers.add_parser("list", help="List configured lumberjacks")

    # sase axe lumberjack run <name>
    axe_lumberjack_run_parser = axe_lumberjack_subparsers.add_parser(
        "run", help="Run a single lumberjack in the foreground"
    )
    axe_lumberjack_run_parser.add_argument(
        "lumberjack_name", help="Name of the lumberjack to run"
    )
    # These flags are forwarded by the orchestrator when spawning lumberjacks
    axe_lumberjack_run_parser.add_argument(
        "-q",
        "--query",
        default="",
        help="Query string for filtering ChangeSpecs",
    )
    axe_lumberjack_run_parser.add_argument(
        "--max-hook-runners",
        type=int,
        default=None,
        help="Maximum concurrent hook runners",
    )
    axe_lumberjack_run_parser.add_argument(
        "--max-agent-runners",
        type=int,
        default=None,
        help="Maximum concurrent agent runners",
    )
    axe_lumberjack_run_parser.add_argument(
        "--zombie-timeout",
        type=int,
        default=None,
        help="Zombie detection timeout in seconds",
    )

    # sase axe lumberjack status
    axe_lumberjack_subparsers.add_parser(
        "status", help="Show status of all lumberjacks"
    )

    # --- bead ---
    bead_parser = top_level_subparsers.add_parser(
        "bead",
        help="Lightweight git-native issue tracking",
    )
    bead_subparsers = bead_parser.add_subparsers(
        dest="bead_subcommand", help="Bead subcommands"
    )

    # sase bead blocked
    bead_subparsers.add_parser("blocked", help="Show blocked issues")

    # sase bead close
    bead_close_parser = bead_subparsers.add_parser(
        "close", help="Close one or more issues"
    )
    bead_close_parser.add_argument("ids", nargs="+", help="Issue IDs to close")
    bead_close_parser.add_argument("--reason", help="Close reason")

    # sase bead create
    bead_create_parser = bead_subparsers.add_parser("create", help="Create a new issue")
    bead_create_parser.add_argument("--title", required=True, help="Issue title")
    bead_create_parser.add_argument(
        "--plan", help="Path to plan file (creates a plan bead linked to this file)"
    )
    bead_create_parser.add_argument(
        "--parent", help="Parent bead ID (creates a phase bead as child of this parent)"
    )
    bead_create_parser.add_argument("--description", help="Issue description")
    bead_create_parser.add_argument("--assignee", help="Assignee")

    # sase bead dep
    bead_dep_parser = bead_subparsers.add_parser("dep", help="Manage dependencies")
    bead_dep_subparsers = bead_dep_parser.add_subparsers(dest="dep_action")
    bead_dep_add_parser = bead_dep_subparsers.add_parser("add", help="Add a dependency")
    bead_dep_add_parser.add_argument("issue", help="Issue that depends on another")
    bead_dep_add_parser.add_argument("depends_on", help="Issue being depended on")

    # sase bead doctor
    bead_subparsers.add_parser("doctor", help="Run health checks")

    # sase bead init
    bead_subparsers.add_parser("init", help="Create .sase_beads/ in current directory")

    # sase bead list
    bead_list_parser = bead_subparsers.add_parser("list", help="List issues")
    bead_list_parser.add_argument(
        "--status",
        choices=["open", "in_progress", "closed"],
        help="Filter by status",
    )
    bead_list_parser.add_argument(
        "--type", choices=["plan", "phase"], help="Filter by type"
    )

    # sase bead onboard
    bead_subparsers.add_parser("onboard", help="Show quick-start guide")

    # sase bead ready
    bead_subparsers.add_parser("ready", help="Show issues ready to work")

    # sase bead rm
    bead_rm_parser = bead_subparsers.add_parser(
        "rm", help="Remove an issue and all its children"
    )
    bead_rm_parser.add_argument("id", help="Issue ID to remove")

    # sase bead show
    bead_show_parser = bead_subparsers.add_parser("show", help="Show issue details")
    bead_show_parser.add_argument("id", help="Issue ID")

    # sase bead stats
    bead_subparsers.add_parser("stats", help="Show project statistics")

    # sase bead sync
    bead_sync_parser = bead_subparsers.add_parser("sync", help="Sync with git")
    bead_sync_parser.add_argument(
        "--status", action="store_true", help="Just check sync status"
    )

    # sase bead update
    bead_update_parser = bead_subparsers.add_parser("update", help="Update an issue")
    bead_update_parser.add_argument("id", help="Issue ID")
    bead_update_parser.add_argument(
        "--status", choices=["open", "in_progress", "closed"]
    )
    bead_update_parser.add_argument("--title")
    bead_update_parser.add_argument("--description")
    bead_update_parser.add_argument("--notes")
    bead_update_parser.add_argument("--design")
    bead_update_parser.add_argument("--assignee")

    # --- amend ---
    amend_parser = top_level_subparsers.add_parser(
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
        "--chat",
        dest="chat_path",
        help="Path to the chat file associated with this amend.",
    )
    amend_parser.add_argument(
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
        "--target-dir",
        dest="target_dir",
        help="Directory to run commands in (default: current directory).",
    )
    amend_parser.add_argument(
        "--timestamp",
        help="Shared timestamp for synced chat/diff files (YYmmdd_HHMMSS format).",
    )

    # --- commit ---
    commit_parser = top_level_subparsers.add_parser(
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
        "--timestamp",
        help="Shared timestamp for synced chat/diff files (YYmmdd_HHMMSS format).",
    )
    commit_parser.add_argument(
        "--end-timestamp",
        dest="end_timestamp",
        help="End timestamp for duration calculation (YYmmdd_HHMMSS format).",
    )

    # --- init-git ---
    init_git_parser = top_level_subparsers.add_parser(
        "init-git",
        help="Initialize a new bare-repo-backed git project",
    )
    init_git_parser.add_argument(
        "project_name",
        help="Name of the project to initialize",
    )
    # Options for 'init-git' (keep sorted alphabetically by long option name)
    init_git_parser.add_argument(
        "--bare-dir",
        default=None,
        help="Override bare repo path (default: ~/.sase/repos/<name>.git)",
    )
    init_git_parser.add_argument(
        "--clone-dir",
        default=None,
        help="Override clone path (default: ~/projects/git/<name>/)",
    )
    init_git_parser.add_argument(
        "--existing",
        default=None,
        help="Path to an existing bare repo to register instead of creating new",
    )

    # --- logs ---
    logs_parser = top_level_subparsers.add_parser(
        "logs",
        help="Collect logs and runtime data for a date range into a pack directory",
    )
    logs_parser.add_argument(
        "daterange",
        help="Date range to collect. Formats: YYmmdd, YYmmddHHMMSS, -Nd, 0d, "
        "START..END (e.g., -7d..0d, 260315..260318, -7d)",
    )

    # --- notify ---
    notify_parser = top_level_subparsers.add_parser(
        "notify",
        help="Create a notification (reads JSON from stdin or uses flags)",
    )
    notify_parser.add_argument(
        "--sender",
        default=None,
        help="Notification sender name (overrides sender in JSON input)",
    )

    # --- path ---
    path_parser = top_level_subparsers.add_parser(
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

    # --- plan ---
    plan_parser = top_level_subparsers.add_parser(
        "plan",
        help="Submit a plan file for approval (used by /sase_plan skill)",
    )
    plan_parser.add_argument("plan_file", help="Path to the plan .md file")

    # --- questions ---
    questions_parser = top_level_subparsers.add_parser(
        "questions",
        help="Ask the user questions (used by /sase_questions skill)",
    )
    questions_parser.add_argument(
        "questions_json", help="JSON string containing questions"
    )

    # --- restore ---
    restore_parser = top_level_subparsers.add_parser(
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

    # --- search ---
    search_parser = top_level_subparsers.add_parser(
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

    # --- revert ---
    revert_parser = top_level_subparsers.add_parser(
        "revert",
        help="Revert a ChangeSpec by pruning its CL and archiving the diff",
    )
    revert_parser.add_argument(
        "name",
        help="NAME of the ChangeSpec to revert",
    )

    # --- run ---
    run_parser = top_level_subparsers.add_parser(
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

    # --- xprompt ---
    xprompt_parser = top_level_subparsers.add_parser(
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
        "--format",
        choices=["mermaid", "text"],
        default="mermaid",
        help="Output format (default: mermaid)",
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
        "--arg",
        action="append",
        dest="named_args",
        metavar="KEY=VALUE",
        help="Named argument (can be repeated).",
    )

    return parser
