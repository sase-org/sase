"""Argument parser definition for the 'agent' CLI subcommand."""

import argparse


def register_agent_parser(subparsers: argparse._SubParsersAction) -> None:
    """Register the 'agent' subcommand parser."""
    agents_parser = subparsers.add_parser(
        "agent",
        description=(
            "Inspect and manage agents across projects. Running bare `sase agent` "
            "delegates to `sase agent list`."
        ),
        help="List, inspect, synchronize, and manage agents across projects",
    )
    agents_sub = agents_parser.add_subparsers(
        dest="agent_subcommand", help="Agent subcommands"
    )

    # sase agent list (default when no subcommand given)
    list_parser = agents_sub.add_parser(
        "list",
        help="List running agents (pretty table by default, JSON with -j)",
    )
    list_parser.add_argument(
        "-a",
        "--all",
        action="store_true",
        help=(
            "Include recently-completed DONE/FAILED agents"
            " (capped at 50 most-recent per project)"
        ),
    )
    list_parser.add_argument(
        "-j",
        "--json",
        action="store_true",
        help="Emit a machine-readable JSON array (stable schema)",
    )
    list_parser.add_argument(
        "-p",
        "--project",
        help="Only show agents for the given project name",
    )

    # sase agent kill -n NAME
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

    # sase agent show -n NAME
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

    # sase agent retire-v1
    retire_v1_parser = agents_sub.add_parser(
        "retire-v1",
        help="Safely retire this machine's legacy-v1 sidecar payload",
        description=(
            "Preview retirement of this machine's legacy-v1 agents-sidecar "
            "payload. Retirement is refused unless the current owner's v2 "
            "manifest covers every v1 hood. The command is a dry run unless "
            "--apply is explicitly supplied."
        ),
    )
    retire_v1_parser.add_argument(
        "-a",
        "--apply",
        action="store_true",
        help="Remove the covered payload, then commit and push through agents sync",
    )
    retire_v1_parser.add_argument(
        "-j",
        "--json",
        action="store_true",
        help="Emit a stable machine-readable JSON report",
    )
    retire_v1_parser.add_argument(
        "-p",
        "--project",
        action="append",
        default=[],
        help="Limit to a project name or alias (repeatable)",
    )

    # sase agent sync
    sync_parser = agents_sub.add_parser(
        "sync",
        help="Run full-duplex agent-sidecar sync or inspect cached incoming status",
        description=(
            "Without flags, fetch and reconcile enabled agents sidecars, import "
            "foreign history, drain publication retries, publish locally "
            "commit-eligible hoods, and push. --check is local and network-free; "
            "--check --refresh fetches and validates incoming remote hoods without "
            "importing or publishing them."
        ),
    )
    sync_parser.add_argument(
        "-c",
        "--check",
        action="store_true",
        help=(
            "Reconcile cached incoming status and receipts without network, "
            "import, publication, commit, or push"
        ),
    )
    sync_parser.add_argument(
        "-d",
        "--drop-retired",
        action="store_true",
        help=(
            "Drop publication requests that were retired as unpublishable, "
            "reporting how many were dropped and why"
        ),
    )
    sync_parser.add_argument(
        "-j",
        "--json",
        action="store_true",
        help="Emit stable machine-readable JSON instead of a colored table",
    )
    sync_parser.add_argument(
        "-p",
        "--project",
        action="append",
        default=[],
        help="Limit to a project name or alias (repeatable)",
    )
    sync_parser.add_argument(
        "-r",
        "--refresh",
        action="store_true",
        help=(
            "With --check, fetch remote refs and validate/cache incoming hoods "
            "without importing them"
        ),
    )
    sync_parser.add_argument(
        "-q",
        "--retry-quarantined",
        action="store_true",
        help=(
            "Clear quarantined publication requests and retry them during "
            "this full sync"
        ),
    )

    # sase agent tribe {list,set,unset}
    tribe_parser = agents_sub.add_parser(
        "tribe",
        help="Manage the user-defined tribe on an agent (used by the Agents tab)",
    )
    tribe_sub = tribe_parser.add_subparsers(
        dest="tribe_subcommand",
        help="Tribe subcommands",
    )

    tribe_set_parser = tribe_sub.add_parser(
        "set",
        help="Set the tribe on an agent (replaces any previous tribe)",
    )
    tribe_set_parser.add_argument(
        "-n",
        "--name",
        required=True,
        help="Name of the agent to assign to a tribe",
    )
    tribe_set_parser.add_argument(
        "-t",
        "--tribe",
        required=True,
        help="Tribe name (without '@')",
    )

    tribe_unset_parser = tribe_sub.add_parser(
        "unset",
        help="Clear the tribe on an agent",
    )
    tribe_unset_parser.add_argument(
        "-n",
        "--name",
        required=True,
        help="Name of the agent to remove from its tribe",
    )

    tribe_list_parser = tribe_sub.add_parser(
        "list",
        help="Print tribes as JSON (all agents, or filtered by --name)",
    )
    tribe_list_parser.add_argument(
        "-n",
        "--name",
        default=None,
        help="Limit output to a single agent",
    )

    # sase agent archive {rebuild-index,verify}
    archive_parser = agents_sub.add_parser(
        "archive",
        help="Maintain dismissed-agent archive indexes",
    )
    archive_sub = archive_parser.add_subparsers(
        dest="archive_subcommand",
        help="Archive maintenance subcommands",
    )

    archive_sub.add_parser(
        "rebuild-index",
        help="Rebuild the dismissed bundle summary index",
    )
    archive_sub.add_parser(
        "verify",
        help="Verify the dismissed bundle summary index",
    )

    # sase agent artifacts layout {migrate,rollback,status,verify}
    artifacts_parser = agents_sub.add_parser(
        "artifacts",
        help="Inspect and migrate agent artifact storage",
    )
    artifacts_sub = artifacts_parser.add_subparsers(
        dest="artifacts_subcommand",
        help="Artifact subcommands",
    )
    layout_parser = artifacts_sub.add_parser(
        "layout",
        help="Manage the ace-run physical artifact layout",
    )
    layout_sub = layout_parser.add_subparsers(
        dest="layout_subcommand",
        help="Layout subcommands",
    )
    for command, help_text in (
        ("migrate", "Move flat ace-run artifact dirs into day shards"),
        ("rollback", "Move migrated ace-run artifact dirs back from a manifest"),
        ("status", "Report ace-run layout counts and index alias status"),
        ("verify", "Verify ace-run layout state against a manifest"),
    ):
        layout_command = layout_sub.add_parser(command, help=help_text)
        if command == "migrate":
            layout_command.add_argument(
                "-d",
                "--dry-run",
                action="store_true",
                help="Write or print the migration manifest without moving dirs",
            )
        layout_command.add_argument(
            "-i",
            "--index-path",
            default=None,
            help="SQLite index path (default: ~/.sase/agent_artifact_index.sqlite)",
        )
        layout_command.add_argument(
            "-j",
            "--json",
            action="store_true",
            help="Emit a machine-readable JSON object",
        )
        if command == "migrate":
            layout_command.add_argument(
                "-l",
                "--limit",
                type=int,
                default=None,
                help="Migrate at most N artifact dirs",
            )
        if command in {"migrate", "rollback", "verify"}:
            layout_command.add_argument(
                "-m",
                "--manifest",
                default=None,
                help="Manifest path for migration, verification, or rollback",
            )
        layout_command.add_argument(
            "-P",
            "--project",
            default=None,
            help="Limit to one project",
        )
        layout_command.add_argument(
            "-p",
            "--projects-root",
            default=None,
            help="Projects artifact root (default: ~/.sase/projects)",
        )

    # sase agent index {gc,rebuild,repair,status,verify}
    index_parser = agents_sub.add_parser(
        "index",
        help="Manage the persistent agent artifact index",
    )
    index_sub = index_parser.add_subparsers(
        dest="index_subcommand", help="Index subcommands"
    )
    gc_parser = index_sub.add_parser(
        "gc",
        help="Reconcile stale artifact-index rows and dismissed identities",
    )
    gc_parser.add_argument(
        "-i",
        "--index-path",
        default=None,
        help="SQLite index path (default: ~/.sase/agent_artifact_index.sqlite)",
    )
    gc_parser.add_argument(
        "-j",
        "--json",
        action="store_true",
        help="Emit a machine-readable JSON object",
    )
    gc_parser.add_argument(
        "-p",
        "--projects-root",
        default=None,
        help="Projects artifact root (default: ~/.sase/projects)",
    )
    gc_parser.add_argument(
        "-r",
        "--purge-revived-bundles",
        action="store_true",
        help=(
            "Before rebuilding, purge dismissed-bundle files and summary rows "
            "for already-revived agents (suffixes absent from "
            "dismissed_agents.json) so they stop re-hiding on rebuild"
        ),
    )
    rebuild_parser = index_sub.add_parser(
        "rebuild",
        help="Rebuild the persistent agent artifact index from artifacts",
    )
    rebuild_parser.add_argument(
        "-i",
        "--index-path",
        default=None,
        help="SQLite index path (default: ~/.sase/agent_artifact_index.sqlite)",
    )
    rebuild_parser.add_argument(
        "-j",
        "--json",
        action="store_true",
        help="Emit a machine-readable JSON object",
    )
    rebuild_parser.add_argument(
        "-p",
        "--projects-root",
        default=None,
        help="Projects artifact root (default: ~/.sase/projects)",
    )
    repair_parser = index_sub.add_parser(
        "repair",
        help="Purge invalid future-dated state from historical agent imports",
        description=(
            "Find future-dated imported artifacts, dismissed bundles, index and "
            "name-registry rows, and import journals. The command is a dry run "
            "unless --apply is provided."
        ),
    )
    repair_parser.add_argument(
        "-a",
        "--apply",
        action="store_true",
        help="Apply the repair (default: report candidates without changing state)",
    )
    repair_parser.add_argument(
        "-i",
        "--index-path",
        default=None,
        help="SQLite index path (default: ~/.sase/agent_artifact_index.sqlite)",
    )
    repair_parser.add_argument(
        "-j",
        "--json",
        action="store_true",
        help="Emit a machine-readable JSON object",
    )
    repair_parser.add_argument(
        "-p",
        "--projects-root",
        default=None,
        help="Projects artifact root (default: ~/.sase/projects)",
    )
    status_parser = index_sub.add_parser(
        "status",
        help="Inspect visible-inbox index health without scanning artifacts",
    )
    status_parser.add_argument(
        "-i",
        "--index-path",
        default=None,
        help="SQLite index path (default: ~/.sase/agent_artifact_index.sqlite)",
    )
    status_parser.add_argument(
        "-j",
        "--json",
        action="store_true",
        help="Emit a machine-readable JSON object",
    )
    status_parser.add_argument(
        "-p",
        "--projects-root",
        default=None,
        help="Projects artifact root (default: ~/.sase/projects)",
    )
    verify_parser = index_sub.add_parser(
        "verify",
        help="Verify the persistent agent artifact index against artifacts",
    )
    verify_parser.add_argument(
        "-i",
        "--index-path",
        default=None,
        help="SQLite index path (default: ~/.sase/agent_artifact_index.sqlite)",
    )
    verify_parser.add_argument(
        "-j",
        "--json",
        action="store_true",
        help="Emit a machine-readable JSON object",
    )
    verify_parser.add_argument(
        "-p",
        "--projects-root",
        default=None,
        help="Projects artifact root (default: ~/.sase/projects)",
    )

    # sase agent names migrate-auto
    names_parser = agents_sub.add_parser(
        "names",
        help="Maintain the permanent agent-name registry and migrations",
    )
    names_sub = names_parser.add_subparsers(
        dest="names_subcommand", help="Name maintenance subcommands"
    )
    migrate_auto_parser = names_sub.add_parser(
        "migrate-auto",
        help="Run the historical auto-name namespace migration",
    )
    migrate_auto_parser.add_argument(
        "-f",
        "--force",
        action="store_true",
        help="Run even when the migration marker says it already completed",
    )
    migrate_auto_parser.add_argument(
        "-j",
        "--json",
        action="store_true",
        help="Emit a machine-readable JSON object",
    )
