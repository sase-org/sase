"""Argument parser definition for the ``sase changespec`` command group."""

import argparse


def register_changespec_parser(subparsers: argparse._SubParsersAction) -> None:
    """Register the 'changespec' subcommand parser."""
    cs_parser = subparsers.add_parser(
        "changespec",
        help="Inspect and maintain ChangeSpecs",
    )
    cs_subparsers = cs_parser.add_subparsers(
        dest="changespec_subcommand", help="ChangeSpec subcommands"
    )

    # sase changespec current [-f FORMAT] [-p <project_file>]
    current_parser = cs_subparsers.add_parser(
        "current",
        help="Show the ChangeSpec associated with the current VCS checkout",
    )
    current_parser.add_argument(
        "-f",
        "--format",
        choices=["markdown", "plain", "json"],
        default="markdown",
        help="Output format (default: markdown)",
    )
    current_parser.add_argument(
        "-p",
        "--project-file",
        dest="project_file",
        default=None,
        help="Path to the project .sase file (default: inferred from current workspace)",
    )

    # sase changespec ref
    ref_parser = cs_subparsers.add_parser(
        "ref",
        help="Inspect and manage artifact references",
        description=(
            "Inspect and manage ChangeSpec artifact references. Invoking "
            "'sase changespec ref' without a subcommand delegates to "
            "'sase changespec ref list'."
        ),
    )
    ref_subparsers = ref_parser.add_subparsers(dest="ref_action")

    ref_add_parser = ref_subparsers.add_parser("add", help="Attach artifact references")
    ref_add_parser.add_argument(
        "-c",
        "--changespec",
        help="Target ChangeSpec (default: current checkout)",
    )
    ref_add_parser.add_argument(
        "refs",
        nargs="+",
        help="Artifact references to attach",
    )

    ref_list_parser = ref_subparsers.add_parser("list", help="List artifact references")
    ref_list_parser.add_argument(
        "-c",
        "--changespec",
        help="Target ChangeSpec (default: current checkout)",
    )
    ref_list_parser.add_argument(
        "-j",
        "--json",
        action="store_true",
        help="Emit machine-readable reference data",
    )
    ref_list_parser.add_argument(
        "-r",
        "--resolve",
        action="store_true",
        help="Resolve references against the current workspace",
    )

    ref_rm_parser = ref_subparsers.add_parser("rm", help="Detach artifact references")
    ref_rm_parser.add_argument(
        "-c",
        "--changespec",
        help="Target ChangeSpec (default: current checkout)",
    )
    ref_rm_parser.add_argument(
        "refs",
        nargs="+",
        help="Artifact references to detach",
    )

    # sase changespec search <query> [-f FORMAT]
    search_parser = cs_subparsers.add_parser(
        "search",
        help="Search for ChangeSpecs matching a query and display them",
    )
    search_parser.add_argument(
        "query",
        help="Query string for filtering ChangeSpecs. "
        "Examples: '\"feature\" AND \"Ready\"', '+myproject', '!!! OR @@@'",
    )
    search_parser.add_argument(
        "-f",
        "--format",
        choices=["plain", "rich", "markdown"],
        default="rich",
        help="Output format: 'plain' for simple text, 'rich' for styled panels, "
        "'markdown' for agent-friendly markdown (default: rich)",
    )

    # sase changespec sync-deltas -c <cl_name> [-p <project_file>]
    sync_deltas_parser = cs_subparsers.add_parser(
        "sync-deltas",
        help="Recompute the DELTAS field for a ChangeSpec from the live VCS state",
    )
    sync_deltas_parser.add_argument(
        "-c",
        "--cl",
        dest="cl_name",
        required=True,
        help="NAME of the ChangeSpec whose DELTAS should be recomputed",
    )
    sync_deltas_parser.add_argument(
        "-p",
        "--project-file",
        dest="project_file",
        default=None,
        help="Path to the project .sase file (default: inferred from current workspace)",
    )
    sync_deltas_parser.add_argument(
        "-w",
        "--workspace-dir",
        dest="workspace_dir",
        default=None,
        help="VCS workspace directory to query (default: current directory)",
    )

    # sase changespec migrate-extension [--force] [--projects-dir DIR]
    migrate_parser = cs_subparsers.add_parser(
        "migrate-extension",
        help=(
            "Rename legacy .gp project spec files under ~/.sase/projects to "
            "the canonical .sase extension"
        ),
    )
    migrate_parser.add_argument(
        "--force",
        action="store_true",
        help=(
            "Replace an existing canonical .sase sibling whose contents differ "
            "from the legacy .gp file. Default policy is to report the "
            "conflict and skip the file."
        ),
    )
    migrate_parser.add_argument(
        "--projects-dir",
        dest="projects_dir",
        default=None,
        help=(
            "Override the ~/.sase/projects/ root that is scanned for legacy "
            "spec files. Primarily useful for testing."
        ),
    )
