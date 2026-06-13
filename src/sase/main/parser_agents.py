"""Argument parser definition for the 'agents' CLI subcommand."""

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

    # sase agents tag {set,unset,list}
    tag_parser = agents_sub.add_parser(
        "tag",
        help="Manage the user-defined tag on an agent (used by the Agents tab)",
    )
    tag_sub = tag_parser.add_subparsers(dest="tag_subcommand", help="Tag subcommands")

    tag_set_parser = tag_sub.add_parser(
        "set",
        help="Set the tag on an agent (replaces any previous tag)",
    )
    tag_set_parser.add_argument(
        "-n",
        "--name",
        required=True,
        help="Name of the agent to tag",
    )
    tag_set_parser.add_argument(
        "-t",
        "--tag",
        required=True,
        help="Tag name (without '@')",
    )

    tag_unset_parser = tag_sub.add_parser(
        "unset",
        help="Clear the tag on an agent",
    )
    tag_unset_parser.add_argument(
        "-n",
        "--name",
        required=True,
        help="Name of the agent to untag",
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

    # sase agents archive {rebuild-index,verify}
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

    # sase agents artifacts layout {migrate,rollback,status,verify}
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

    # sase agents index {gc,rebuild,status,verify}
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
        "-p",
        "--projects-root",
        default=None,
        help="Projects artifact root (default: ~/.sase/projects)",
    )
    gc_parser.add_argument(
        "-j",
        "--json",
        action="store_true",
        help="Emit a machine-readable JSON object",
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
        "-p",
        "--projects-root",
        default=None,
        help="Projects artifact root (default: ~/.sase/projects)",
    )
    rebuild_parser.add_argument(
        "-j",
        "--json",
        action="store_true",
        help="Emit a machine-readable JSON object",
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
        "-p",
        "--projects-root",
        default=None,
        help="Projects artifact root (default: ~/.sase/projects)",
    )
    status_parser.add_argument(
        "-j",
        "--json",
        action="store_true",
        help="Emit a machine-readable JSON object",
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
        "-p",
        "--projects-root",
        default=None,
        help="Projects artifact root (default: ~/.sase/projects)",
    )
    verify_parser.add_argument(
        "-j",
        "--json",
        action="store_true",
        help="Emit a machine-readable JSON object",
    )

    # sase agents names migrate-auto
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
