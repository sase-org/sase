"""Argument parser definitions for bead subcommands."""

import argparse


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
    bead_close_parser.add_argument("-r", "--reason", help="Close reason")

    # sase bead create
    bead_create_parser = bead_subparsers.add_parser("create", help="Create a new issue")
    bead_create_parser.add_argument("-t", "--title", required=True, help="Issue title")
    bead_create_parser.add_argument(
        "-T",
        "--type",
        required=True,
        help="Bead type: plan(<plan_file>), plan(<plan_file>,<parent_id>), or phase(<parent_id>)",
    )
    bead_create_parser.add_argument("-d", "--description", help="Issue description")
    bead_create_parser.add_argument("-a", "--assignee", help="Assignee")
    bead_create_parser.add_argument(
        "--tier",
        choices=["plan", "epic", "legend"],
        help="Plan-bead tier (plan, epic, or legend)",
    )
    bead_create_parser.add_argument(
        "-c", "--changespec", help="Attach a ChangeSpec name to a plan bead"
    )
    bead_create_parser.add_argument(
        "-b",
        "--bug-id",
        help="Bug ID to pass when creating the attached ChangeSpec",
    )
    bead_create_parser.add_argument(
        "-E",
        "--epic-count",
        type=int,
        help="Number of epics proposed by a legend plan bead",
    )

    # sase bead dep
    bead_dep_parser = bead_subparsers.add_parser("dep", help="Manage dependencies")
    bead_dep_subparsers = bead_dep_parser.add_subparsers(dest="dep_action")
    bead_dep_add_parser = bead_dep_subparsers.add_parser("add", help="Add a dependency")
    bead_dep_add_parser.add_argument("issue", help="Issue that depends on another")
    bead_dep_add_parser.add_argument("depends_on", help="Issue being depended on")

    # sase bead doctor
    bead_subparsers.add_parser("doctor", help="Run health checks")

    # sase bead init
    bead_subparsers.add_parser("init", help="Create sdd/beads/ in current directory")

    # sase bead list
    bead_list_parser = bead_subparsers.add_parser("list", help="List issues")
    bead_list_parser.add_argument(
        "-s",
        "--status",
        choices=["open", "in_progress", "closed"],
        action="append",
        help="Filter by status (repeatable)",
    )
    bead_list_parser.add_argument(
        "-t",
        "--type",
        choices=["plan", "phase"],
        action="append",
        help="Filter by type (repeatable)",
    )
    bead_list_parser.add_argument(
        "--tier",
        choices=["plan", "epic", "legend"],
        action="append",
        help="Filter by plan-bead tier (repeatable)",
    )

    # sase bead onboard
    bead_subparsers.add_parser("onboard", help="Show quick-start guide")

    # sase bead open
    bead_open_parser = bead_subparsers.add_parser("open", help="Reopen an issue")
    bead_open_parser.add_argument("id", help="Issue ID to reopen")

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
        "-s", "--status", action="store_true", help="Just check sync status"
    )

    # sase bead work
    bead_work_parser = bead_subparsers.add_parser(
        "work",
        help="Mark an epic plan bead ready and launch its phase + land agents",
    )
    bead_work_parser.add_argument("id", help="Epic plan bead ID")
    bead_work_parser.add_argument(
        "-n",
        "--dry-run",
        action="store_true",
        help="Print the wave plan and rendered multi-prompt without mutating state or launching",
    )
    bead_work_parser.add_argument(
        "-y",
        "--yes",
        action="store_true",
        help="Skip the launch confirmation prompt",
    )

    # sase bead update
    bead_update_parser = bead_subparsers.add_parser("update", help="Update an issue")
    bead_update_parser.add_argument("id", help="Issue ID")
    bead_update_parser.add_argument(
        "-s", "--status", choices=["open", "in_progress", "closed"]
    )
    bead_update_parser.add_argument("-t", "--title")
    bead_update_parser.add_argument("-d", "--description")
    bead_update_parser.add_argument("-n", "--notes")
    bead_update_parser.add_argument("-D", "--design")
    bead_update_parser.add_argument("-a", "--assignee")
    bead_update_parser.add_argument("--tier", choices=["plan", "epic", "legend"])
    bead_update_parser.add_argument("-E", "--epic-count", type=int)
