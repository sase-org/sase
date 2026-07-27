"""Argument parser definitions for bead subcommands."""

import argparse


def nonnegative_int(value: str) -> int:
    parsed = int(value)
    if parsed < 0:
        raise argparse.ArgumentTypeError("must be a non-negative integer")
    return parsed


def register_bead_parser(subparsers: argparse._SubParsersAction) -> None:
    """Register the 'bead' subcommand parser."""
    bead_parser = subparsers.add_parser(
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
    bead_close_parser.add_argument(
        "-f",
        "--force",
        action="store_true",
        help=(
            "Close unfinished descendants; requires --reason and a "
            "non-done --resolution"
        ),
    )
    bead_close_parser.add_argument("-r", "--reason", help="Close reason")
    bead_close_parser.add_argument(
        "-R",
        "--resolution",
        choices=["canceled", "done", "superseded"],
        default="done",
        help="How this bead was resolved (default: done)",
    )

    # sase bead create
    bead_create_parser = bead_subparsers.add_parser("create", help="Create a new issue")
    bead_create_parser.add_argument("-a", "--assignee", help="Assignee")
    bead_create_parser.add_argument(
        "-b",
        "--bug-id",
        help="Bug ID to pass when creating the attached ChangeSpec",
    )
    bead_create_parser.add_argument(
        "-c", "--changespec", help="Attach a ChangeSpec name to a plan bead"
    )
    bead_create_parser.add_argument("-d", "--description", help="Issue description")
    bead_create_parser.add_argument(
        "-m",
        "--model",
        help=(
            "Model to use when this bead is launched. Provider-qualified "
            "(e.g. codex/gpt-5.6-sol) or local alias (e.g. #pro). For epic "
            "plan beads this becomes the land-agent model; for phase beads it "
            "is the per-phase work model."
        ),
    )
    bead_create_parser.add_argument(
        "-z",
        "--size",
        choices=["xsmall", "small", "medium", "large", "xlarge"],
        help="Phase size controlling plan-first prompting and default model routing",
    )
    bead_create_parser.add_argument(
        "-r",
        "--tier",
        choices=["plan", "epic"],
        help="Plan-bead tier (plan or epic)",
    )
    bead_create_parser.add_argument("-t", "--title", required=True, help="Issue title")
    bead_create_parser.add_argument(
        "-T",
        "--type",
        required=True,
        help="Bead type: plan(<plan_file>), plan(<plan_file>,<parent_id>), or phase(<parent_id>)",
    )

    # sase bead dep
    bead_dep_parser = bead_subparsers.add_parser(
        "dep",
        help="Inspect and manage dependencies",
        description=(
            "Inspect and manage dependency edges. Invoking 'sase bead dep' "
            "without a subcommand delegates to 'sase bead dep list'."
        ),
    )
    bead_dep_subparsers = bead_dep_parser.add_subparsers(dest="dep_action")
    bead_dep_add_parser = bead_dep_subparsers.add_parser("add", help="Add a dependency")
    bead_dep_add_parser.add_argument("issue", help="Issue that depends on another")
    bead_dep_add_parser.add_argument("depends_on", help="Issue being depended on")
    bead_dep_list_parser = bead_dep_subparsers.add_parser(
        "list",
        help="List dependency edges",
        description=(
            "List dependency edges with blocking state and recorded provenance. "
            "A scoped read includes every status by default; a store-wide read "
            "defaults to open, claimed, and in-progress beads."
        ),
    )
    bead_dep_list_parser.add_argument("id", nargs="?", help="Issue ID")
    bead_dep_list_parser.add_argument(
        "-c",
        "--color",
        choices=["always", "auto", "never"],
        default="auto",
        help="Color output: always, auto, or never (default: auto)",
    )
    bead_dep_list_parser.add_argument(
        "-d",
        "--direction",
        choices=["both", "in", "out"],
        default="both",
        help="Edges to show: both, in, or out (default: both)",
    )
    bead_dep_list_parser.add_argument(
        "-f",
        "--format",
        choices=["compact", "full", "json"],
        default="compact",
        help="Output format: compact, full, or json (default: compact)",
    )
    bead_dep_list_parser.add_argument(
        "-n",
        "--limit",
        type=nonnegative_int,
        default=0,
        help="Maximum beads to print; 0 means unlimited",
    )
    bead_dep_list_parser.add_argument(
        "-s",
        "--status",
        choices=["claimed", "closed", "in_progress", "open"],
        action="append",
        help="Filter by status (repeatable)",
    )
    bead_dep_rm_parser = bead_dep_subparsers.add_parser(
        "rm", help="Remove dependencies"
    )
    bead_dep_rm_parser.add_argument("issue", help="Issue that depends on others")
    bead_dep_rm_parser.add_argument(
        "depends_on",
        metavar="depends_on",
        nargs="+",
        help="Issues no longer depended on",
    )
    bead_dep_tree_parser = bead_dep_subparsers.add_parser(
        "tree",
        help="Walk the dependency graph as a tree",
        description=(
            "Walk dependencies, blockers, or both as a deterministic tree. "
            "A scoped tree includes every status by default; a store-wide tree "
            "defaults to open, claimed, and in-progress beads."
        ),
    )
    bead_dep_tree_parser.add_argument("id", nargs="?", help="Issue ID")
    bead_dep_tree_parser.add_argument(
        "-c",
        "--color",
        choices=["always", "auto", "never"],
        default="auto",
        help="Color output: always, auto, or never (default: auto)",
    )
    bead_dep_tree_parser.add_argument(
        "-d",
        "--direction",
        choices=["both", "in", "out"],
        default="out",
        help="Direction to walk: both, in, or out (default: out)",
    )
    bead_dep_tree_parser.add_argument(
        "-f",
        "--format",
        choices=["compact", "full", "json"],
        default="compact",
        help="Output format: compact, full, or json (default: compact)",
    )
    bead_dep_tree_parser.add_argument(
        "-L",
        "--levels",
        type=nonnegative_int,
        default=0,
        help="Maximum levels to descend; 0 means unlimited",
    )
    bead_dep_tree_parser.add_argument(
        "-s",
        "--status",
        choices=["claimed", "closed", "in_progress", "open"],
        action="append",
        help="Filter by status (repeatable)",
    )

    # sase bead doctor
    bead_doctor_parser = bead_subparsers.add_parser(
        "doctor",
        help="Validate bead-store health and design references",
    )
    bead_doctor_parser.add_argument(
        "-F",
        "--fix-design-refs",
        action="store_true",
        help=(
            "Preview and, after confirmation, repair recoverable bead design references"
        ),
    )

    # sase bead history
    bead_history_parser = bead_subparsers.add_parser(
        "history",
        help="Show event history or find overwritten notes",
        description=(
            "Replay the canonical event streams for one bead, or find note "
            "revisions that no longer appear in current notes. Compact "
            "history output shows one row per event; full output shows the "
            "prior and new value for every changed field."
        ),
    )
    bead_history_parser.add_argument(
        "id",
        nargs="?",
        help="Issue ID",
    )
    bead_history_parser.add_argument(
        "-F",
        "--field",
        action="append",
        help="Restrict to events changing this field (repeatable)",
    )
    bead_history_parser.add_argument(
        "-f",
        "--format",
        choices=["compact", "full", "json"],
        default="compact",
        help="Output format: compact, full, or json (default: compact)",
    )
    bead_history_parser.add_argument(
        "-n",
        "--limit",
        type=nonnegative_int,
        default=0,
        help="Newest entries to print; 0 means unlimited",
    )
    bead_history_parser.add_argument(
        "-l",
        "--lost-notes",
        action="store_true",
        help="Report beads whose current notes dropped an earlier revision",
    )
    bead_history_parser.add_argument(
        "-R",
        "--restore",
        action="store_true",
        help="With --lost-notes, re-append dropped revisions after confirmation",
    )

    # sase bead init
    bead_subparsers.add_parser("init", help="Create the effective SDD bead store")

    # sase bead list
    bead_list_parser = bead_subparsers.add_parser(
        "list",
        help="List issues",
        description=(
            "List open, claimed, and in-progress beads by default. If none "
            "match and --status was not provided, list closed beads instead. "
            "Closed listings default to the newest 20 beads unless --limit 0 "
            "is used. Bare 'sase bead' defaults to this command."
        ),
        epilog=(
            "Examples:\n"
            "  sase bead list\n"
            "  sase bead list --status open --type phase\n"
            "  sase bead list --format json\n"
            "  sase bead list --format full --limit 3\n"
            "  sase bead list --status closed --limit 0"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    bead_list_parser.add_argument(
        "-f",
        "--format",
        choices=["compact", "json", "full"],
        default="compact",
        help="Output format: compact, json, or full (default: compact)",
    )
    bead_list_parser.add_argument(
        "-n",
        "--limit",
        type=nonnegative_int,
        default=None,
        help=(
            "Maximum beads to print; closed listings default to 20, 0 means unlimited"
        ),
    )
    bead_list_parser.add_argument(
        "-s",
        "--status",
        choices=["open", "claimed", "in_progress", "closed"],
        action="append",
        help="Filter by status (repeatable)",
    )
    bead_list_parser.add_argument(
        "--tier",
        choices=["plan", "epic"],
        action="append",
        help="Filter by plan-bead tier (repeatable)",
    )
    bead_list_parser.add_argument(
        "-t",
        "--type",
        choices=["plan", "phase"],
        action="append",
        help="Filter by type (repeatable)",
    )

    # sase bead note
    bead_note_parser = bead_subparsers.add_parser(
        "note", help="Append an attributed note entry"
    )
    bead_note_parser.add_argument("id", help="Issue ID")
    bead_note_parser.add_argument(
        "text",
        nargs="+",
        help="Note text to append",
    )
    bead_note_parser.add_argument(
        "-a",
        "--author",
        metavar="NAME",
        help="Author recorded on the entry (default: current agent, else store owner)",
    )

    # sase bead onboard
    bead_subparsers.add_parser("onboard", help="Show quick-start guide")

    # sase bead open
    bead_open_parser = bead_subparsers.add_parser("open", help="Reopen an issue")
    bead_open_parser.add_argument("id", help="Issue ID to reopen")

    # sase bead ready
    bead_subparsers.add_parser("ready", help="Show issues ready to work")

    # sase bead resolve-conflicts
    bead_subparsers.add_parser(
        "resolve-conflicts",
        help="Resolve mechanical git conflicts in sdd/beads event streams",
        description=(
            "Resolve merge or rebase conflicts in generated bead state. "
            "Only sdd/beads/issues.jsonl, events/manifest.json, and "
            "events/streams/*.jsonl conflicts are auto-merged."
        ),
    )

    # sase bead rm
    bead_rm_parser = bead_subparsers.add_parser(
        "rm", help="Remove issues and all their children"
    )
    bead_rm_parser.add_argument(
        "ids", nargs="+", help="One or more issue IDs to remove"
    )

    # sase bead search
    bead_search_parser = bead_subparsers.add_parser(
        "search",
        help="Search issues by text",
        description=(
            "Find beads whose human-readable fields contain a literal query "
            "string. Searches open, claimed, in-progress, and closed beads by default."
        ),
        epilog=(
            "Examples:\n"
            "  sase bead search auth\n"
            "  sase bead search auth --format json\n"
            "  sase bead search auth --format full --limit 3\n"
            "  sase bead search auth --status open --type phase"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    bead_search_parser.add_argument(
        "query",
        help="Literal non-empty text to search for",
    )
    bead_search_parser.add_argument(
        "-c",
        "--color",
        choices=["auto", "always", "never"],
        default="auto",
        help="Color output: auto, always, or never (default: auto)",
    )
    bead_search_parser.add_argument(
        "-f",
        "--format",
        choices=["compact", "json", "full"],
        default="compact",
        help="Output format: compact, json, or full (default: compact)",
    )
    bead_search_parser.add_argument(
        "-n",
        "--limit",
        type=nonnegative_int,
        default=None,
        help="Maximum results to print; 0 means unlimited",
    )
    bead_search_parser.add_argument(
        "-s",
        "--status",
        choices=["open", "claimed", "in_progress", "closed"],
        action="append",
        help="Filter by status (repeatable)",
    )
    bead_search_parser.add_argument(
        "--tier",
        choices=["plan", "epic"],
        action="append",
        help="Filter by plan-bead tier (repeatable)",
    )
    bead_search_parser.add_argument(
        "-t",
        "--type",
        choices=["plan", "phase"],
        action="append",
        help="Filter by type (repeatable)",
    )

    # sase bead show
    bead_show_parser = bead_subparsers.add_parser(
        "show",
        help="Show issue details",
        description=(
            "Show one bead's full detail block: status, type, tier, owner, "
            "assignee, model, phase size, parent lineage, children, "
            "dependencies, blockers, description, notes, ChangeSpec, and the "
            "linked plan. --format compact prints the same single row as "
            "'sase bead list'; --format json adds the resolved parent, child, "
            "dependency, blocker, and plan graph as machine-readable data."
        ),
        epilog=(
            "Examples:\n"
            "  sase bead show sase-64\n"
            "  sase bead show sase-64 --format compact\n"
            "  sase bead show sase-64 --format json"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    bead_show_parser.add_argument(
        "-f",
        "--format",
        choices=["compact", "json", "full"],
        default="full",
        help="Output format: compact, json, or full (default: full)",
    )
    bead_show_parser.add_argument("id", help="Issue ID")

    # sase bead stats
    bead_subparsers.add_parser("stats", help="Show project statistics")

    # sase bead sync
    bead_sync_parser = bead_subparsers.add_parser("sync", help="Sync with git")
    bead_sync_parser.add_argument(
        "-s", "--status", action="store_true", help="Just check sync status"
    )

    # sase bead work
    bead_work_parser = bead_subparsers.add_parser(
        "work",
        help="Create or launch work for an epic plan",
        description=(
            "Launch an existing epic plan bead, or validate an epic Markdown "
            "plan, archive it into the SDD store, create its bead DAG, and "
            "launch its phase and land agents. Plan-file launches are "
            "idempotent and resume from an existing bead_id link."
        ),
        epilog=(
            "Examples:\n"
            "  sase bead work sase-64\n"
            "  sase bead work ./epic_plan.md --dry-run\n"
            "  sase bead work ./epic_plan.md --parent sase-64.2 --yes\n"
            "  sase bead work ./epic_plan.md --parent top-level --yes\n"
            "  sase bead work ./epic_plan.md --yes\n"
            "  sase bead work ./epic_plan.md --yes-to-all\n"
            "  sase bead work ./epic_plan.md --json"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    bead_work_parser.add_argument(
        "target",
        help="Epic bead ID, or path to a validated epic plan file",
    )
    bead_work_parser.add_argument(
        "-a",
        "--artifacts-dir",
        metavar="DIR",
        help="Planner artifacts directory to back-fill after an approved epic launch",
    )
    bead_work_parser.add_argument(
        "-c",
        "--cl-name",
        metavar="NAME",
        help="ChangeSpec name for the approved epic completion notification",
    )
    bead_work_parser.add_argument(
        "-n",
        "--dry-run",
        action="store_true",
        help="Validate and preview the wave plan without changing files, beads, or agents",
    )
    bead_work_parser.add_argument(
        "-j",
        "--json",
        action="store_true",
        help=(
            "Print one machine-readable result object; implies --yes-to-all, "
            "so no confirmation prompt is shown"
        ),
    )
    bead_work_parser.add_argument(
        "-P",
        "--no-push",
        action="store_true",
        help="Commit plan and bead state locally but skip post-commit pushes",
    )
    bead_work_parser.add_argument(
        "-p",
        "--parent",
        metavar="BEAD_ID|top-level",
        help=(
            "Override a plan file's parent_bead; use 'top-level' to create "
            "an unparented epic"
        ),
    )
    bead_work_parser.add_argument(
        "-y",
        "--yes",
        action="store_true",
        help="Skip only the launch confirmation prompt",
    )
    bead_work_parser.add_argument(
        "-Y",
        "--yes-to-all",
        action="store_true",
        help="Skip both destructive-cleanup and launch confirmation prompts",
    )

    # sase bead update
    bead_update_parser = bead_subparsers.add_parser("update", help="Update an issue")
    bead_update_parser.add_argument("id", help="Issue ID")
    bead_update_parser.add_argument("-a", "--assignee")
    bead_update_parser.add_argument("-D", "--design")
    bead_update_parser.add_argument("-d", "--description")
    bead_update_parser.add_argument(
        "-m",
        "--model",
        help=(
            "Model for this bead's launch. Provider-qualified (e.g. "
            "codex/gpt-5.6-sol) or local alias (e.g. #pro). Pass '' to clear."
        ),
    )
    bead_update_parser.add_argument("-n", "--notes")
    bead_update_parser.add_argument(
        "-z",
        "--size",
        choices=["xsmall", "small", "medium", "large", "xlarge"],
        help="Phase size controlling plan-first prompting and default model routing",
    )
    bead_update_parser.add_argument(
        "-s",
        "--status",
        choices=["open", "claimed", "in_progress", "closed"],
    )
    bead_update_parser.add_argument("-r", "--tier", choices=["plan", "epic"])
    bead_update_parser.add_argument("-t", "--title")
