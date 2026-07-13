"""Argument parser definition for the ``sase repo`` CLI command."""

from __future__ import annotations

import argparse


def register_repo_parser(subparsers: argparse._SubParsersAction) -> None:
    """Register repository inventory and workflow commands."""

    repo_parser = subparsers.add_parser(
        "repo",
        help="Inspect repositories and repository-open activity",
        description=(
            "Inspect repositories known by SASE. Running `sase repo` defaults "
            "to `sase repo list`."
        ),
    )
    repo_sub = repo_parser.add_subparsers(
        dest="repo_subcommand",
        help="Repository subcommands",
    )
    list_parser = repo_sub.add_parser(
        "list",
        help="List repositories and their per-workspace clone status",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        description=(
            "List primary, sidecar, and linked repositories for the current "
            "project and show where they are cloned. The project and workspace "
            "default to the checkout that contains the current directory."
        ),
        epilog=(
            "examples:\n"
            "  sase repo list\n"
            "  sase repo list --workspace 12\n"
            "  sase repo list --project sase --json\n"
            "  sase repo list --all"
        ),
    )
    list_parser.add_argument(
        "-a",
        "--all",
        action="store_true",
        dest="all_projects",
        help="List repos across all enabled and disabled projects",
    )
    list_parser.add_argument(
        "-j",
        "--json",
        action="store_true",
        help="Emit a machine-readable JSON object",
    )
    list_parser.add_argument(
        "-p",
        "--project",
        default=None,
        help="Project to query (default: infer from current directory)",
    )
    list_parser.add_argument(
        "-w",
        "--workspace",
        type=int,
        default=None,
        metavar="N",
        help="Workspace context (default: infer from current directory)",
    )

    log_parser = repo_sub.add_parser(
        "log",
        help="Inspect the repository-open audit log",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        description=(
            "Summarize successful repository opens for one project. Add a "
            "repository, agent, or workspace filter to show matching agents "
            "and individual events; use an event ID prefix for full detail. "
            "The project defaults to the checkout that contains the current "
            "directory."
        ),
        epilog=(
            "examples:\n"
            "  sase repo log\n"
            "  sase repo log --repo sase-core\n"
            "  sase repo log --agent phase-one --workspace 12\n"
            "  sase repo log --id <open-id> --json"
        ),
    )
    log_parser.add_argument(
        "-a",
        "--agent",
        default=None,
        metavar="AGENT_NAME",
        help="Show opens attributed to this agent or interactive user",
    )
    log_parser.add_argument(
        "-i",
        "--id",
        default=None,
        metavar="OPEN_ID",
        help="Show one event by exact ID or unambiguous ID prefix",
    )
    log_parser.add_argument(
        "-j",
        "--json",
        action="store_true",
        help="Emit a deterministic machine-readable JSON object",
    )
    log_parser.add_argument(
        "-p",
        "--project",
        default=None,
        help="Project to query (default: infer from current directory)",
    )
    log_parser.add_argument(
        "-r",
        "--repo",
        default=None,
        metavar="REPO",
        help="Show opens for this repository name",
    )
    log_parser.add_argument(
        "-w",
        "--workspace",
        type=int,
        default=None,
        metavar="N",
        help="Show opens in this workspace number",
    )

    open_parser = repo_sub.add_parser(
        "open",
        help="Prepare a repository checkout and print its path",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        description=(
            "Resolve a primary, sidecar, or linked repository in the host "
            "project, prepare it in one workspace context, and print only "
            "the prepared path. The workspace defaults to the checkout that "
            "contains the current directory."
        ),
        epilog=(
            "examples:\n"
            '  sase repo open chezmoi --reason "Update shared configuration"\n'
            '  sase repo open sase-core -r "Fix the Rust binding" -w 12\n'
            '  sase repo open sase--plans -p sase -r "Review the epic plan"'
        ),
    )
    open_parser.add_argument(
        "repo",
        metavar="REPO",
        help="Repository name shown by `sase repo list`",
    )
    open_parser.add_argument(
        "-p",
        "--project",
        default=None,
        help="Host project (default: infer from current directory)",
    )
    open_parser.add_argument(
        "-r",
        "--reason",
        required=True,
        help="Non-empty reason for the audited repository open",
    )
    open_parser.add_argument(
        "-w",
        "--workspace",
        type=int,
        default=None,
        metavar="N",
        help="Host workspace number (default: infer from current directory)",
    )


__all__ = ["register_repo_parser"]
