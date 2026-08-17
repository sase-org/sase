"""Argument parser definition for the ``sase repo`` CLI command."""

from __future__ import annotations

import argparse

from sase.completion.shorten import set_completion_summary


def register_repo_parser(subparsers: argparse._SubParsersAction) -> None:
    """Register repository inventory and workflow commands."""

    repo_parser = subparsers.add_parser(
        "repo",
        help="Initialize, inspect, resolve, and open repositories",
        description=(
            "Initialize, inspect, and resolve repositories known by SASE. "
            "Running `sase repo` defaults to `sase repo list`."
        ),
    )
    repo_sub = repo_parser.add_subparsers(
        dest="repo_subcommand",
        help="Repository subcommands",
    )
    init_parser = repo_sub.add_parser(
        "init",
        help="Initialize configured sidecars and project repository wiring",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        description=(
            "Declare the managed plans sidecar, initialize every enabled "
            "configured sidecar, and add the tracked /sase/repos/ ignore rule.\n\n"
            "Creating a missing provider repository always requires an "
            "interactive, default-no y/yes confirmation."
        ),
        epilog=(
            "examples:\n"
            "  sase repo init --check\n"
            "  sase repo init --diff --no-commit\n"
            "  sase repo init"
        ),
    )
    init_parser.add_argument(
        "-c",
        "--check",
        action="store_true",
        help="Report sidecar, config, and ignore-rule work without writing files",
    )
    init_parser.add_argument(
        "-d",
        "--diff",
        action="store_true",
        help="Show full file diffs for planned repository changes",
    )
    init_parser.add_argument(
        "-C",
        "--no-commit",
        action="store_true",
        help="Write project config and ignore rules without committing or pushing",
    )

    list_parser = repo_sub.add_parser(
        "list",
        help="List repositories and their per-workspace clone status",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        description=(
            "List primary, sidecar, linked, and opened external repositories "
            "for the current project and show where they are cloned. The project "
            "and workspace default to the checkout that contains the current "
            "directory."
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
        help="Open a repo checkout without cleaning it; print its path",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        description=(
            "Resolve a repository in three tiers: a primary, sidecar, or linked "
            "repository in the host project; another registered SASE project; "
            "or an external provider ref such as gh:owner/repo (owner/repo is "
            "GitHub shorthand). Materialize it in one workspace context without "
            "cleaning, resetting, or synchronizing an existing checkout, then "
            "print only the opened path. The workspace defaults to the checkout "
            "that contains the current directory."
        ),
        epilog=(
            "examples:\n"
            '  sase repo open chezmoi --reason "Update shared configuration"\n'
            '  sase repo open dotdrop -r "Port the launcher fix"\n'
            '  sase repo open gh:pallets/click -r "Study upstream parsing"\n'
            '  sase repo open pallets/click -r "Study upstream parsing"'
        ),
    )
    repo_positional = open_parser.add_argument(
        "repo",
        metavar="REPO",
        help=(
            "Inventory name, registered project name, gh:owner/repo, or "
            "owner/repo shorthand"
        ),
    )
    set_completion_summary(
        repo_positional, "Inventory name, project name, or gh:owner/repo"
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

    path_parser = repo_sub.add_parser(
        "path",
        help="Print a primary or sidecar repository path",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        description=(
            "Resolve a primary or sidecar repository by role name or repository "
            "slug and print exactly one absolute path. Resolution is read-only "
            "unless --ensure is passed. Linked and external repositories must "
            "be prepared with `sase repo open` instead."
        ),
        epilog=(
            "examples:\n"
            "  sase repo path plans\n"
            "  sase repo path research --ensure\n"
            "  sase repo path plans --project sase --workspace 12"
        ),
    )
    path_parser.add_argument(
        "repo",
        metavar="REPO",
        help="Primary name, sidecar role name, or sidecar repository slug",
    )
    path_parser.add_argument(
        "-e",
        "--ensure",
        action="store_true",
        help="Materialize and synchronize the backing sidecar clone",
    )
    path_parser.add_argument(
        "-p",
        "--project",
        default=None,
        help="Project to query (default: infer from current directory)",
    )
    path_parser.add_argument(
        "-w",
        "--workspace",
        type=int,
        default=None,
        metavar="N",
        help="Workspace context (default: infer from current directory)",
    )


__all__ = ["register_repo_parser"]
