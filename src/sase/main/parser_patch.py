"""Argument parser definition for the ``sase patch`` command group.

``sase changespec`` remains a top-level alias for compatibility.
"""

import argparse


class _PatchTargetAction(argparse.Action):
    """Store canonical and legacy target names for Patch-target options."""

    def __call__(
        self,
        parser: argparse.ArgumentParser,
        namespace: argparse.Namespace,
        values: object,
        option_string: str | None = None,
    ) -> None:
        del parser, option_string
        setattr(namespace, self.dest, values)
        namespace.patch = values
        namespace.changespec = values  # legacy parser destination


def _add_patch_target_argument(
    parser: argparse.ArgumentParser,
    *option_strings: str,
    help: str,
    dest: str = "patch",
    required: bool = False,
) -> None:
    parser.add_argument(
        *option_strings,
        dest=dest,
        action=_PatchTargetAction,
        required=required,
        help=help,
    )
    parser.set_defaults(patch=None, changespec=None)  # legacy parser destination


def register_patch_parser(subparsers: argparse._SubParsersAction) -> None:
    """Register the canonical 'patch' subcommand parser."""
    cs_parser = subparsers.add_parser(
        "patch",
        aliases=["changespec"],
        help="Inspect and maintain Patches",
        description="Inspect and maintain Patch lifecycle records.",
    )
    cs_subparsers = cs_parser.add_subparsers(
        dest="patch_subcommand", help="Patch subcommands"
    )
    cs_parser.set_defaults(changespec_subcommand=None)

    # sase patch current [-f FORMAT] [-p <project_file>]
    current_parser = cs_subparsers.add_parser(
        "current",
        help="Show the Patch associated with the current VCS checkout",
    )
    current_parser.set_defaults(changespec_subcommand="current")
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

    # sase patch ref
    ref_parser = cs_subparsers.add_parser(
        "ref",
        help="Inspect and manage artifact references",
        description=(
            "Inspect and manage Patch artifact references. Invoking "
            "'sase patch ref' without a subcommand delegates to "
            "'sase patch ref list'."
        ),
    )
    ref_parser.set_defaults(changespec_subcommand="ref")
    ref_subparsers = ref_parser.add_subparsers(dest="ref_action")

    ref_add_parser = ref_subparsers.add_parser("add", help="Attach artifact references")
    _add_patch_target_argument(
        ref_add_parser,
        "-p",
        "--patch",
        "-c",
        "--changespec",
        help="Target Patch (default: current checkout)",
    )
    ref_add_parser.add_argument(
        "refs",
        nargs="+",
        help="Artifact references to attach",
    )

    ref_list_parser = ref_subparsers.add_parser("list", help="List artifact references")
    _add_patch_target_argument(
        ref_list_parser,
        "-p",
        "--patch",
        "-c",
        "--changespec",
        help="Target Patch (default: current checkout)",
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
    _add_patch_target_argument(
        ref_rm_parser,
        "-p",
        "--patch",
        "-c",
        "--changespec",
        help="Target Patch (default: current checkout)",
    )
    ref_rm_parser.add_argument(
        "refs",
        nargs="+",
        help="Artifact references to detach",
    )

    # sase patch search <query> [-f FORMAT]
    search_parser = cs_subparsers.add_parser(
        "search",
        help="Search for Patches matching a query and display them",
    )
    search_parser.set_defaults(changespec_subcommand="search")
    search_parser.add_argument(
        "query",
        help="Query string for filtering Patches. "
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

    # sase patch set-origin <name> <sase|external|unknown>
    set_origin_parser = cs_subparsers.add_parser(
        "set-origin",
        help="Mark a Patch's PR_ORIGIN (sase, external, or unknown)",
        description=(
            "Deliberately set a Patch's PR_ORIGIN field. This is the manual "
            "half of the tri-state PR_ORIGIN decision: it resolves an "
            "'unknown' record (or corrects a wrong mark) without waiting "
            "for the external_pr_mirror chop."
        ),
    )
    set_origin_parser.set_defaults(changespec_subcommand="set-origin")
    set_origin_parser.add_argument(
        "name",
        help="NAME of the Patch to update",
    )
    set_origin_parser.add_argument(
        "origin",
        choices=["sase", "external", "unknown"],
        help="New PR_ORIGIN value",
    )
    set_origin_parser.add_argument(
        "-p",
        "--project-file",
        dest="project_file",
        default=None,
        help="Path to the project .sase file (default: inferred from current workspace)",
    )

    # sase patch sync-deltas -P <patch_name> [-p <project_file>]
    sync_deltas_parser = cs_subparsers.add_parser(
        "sync-deltas",
        help="Recompute the DELTAS field for a Patch from the live VCS state",
    )
    sync_deltas_parser.set_defaults(changespec_subcommand="sync-deltas")
    _add_patch_target_argument(
        sync_deltas_parser,
        "-P",
        "--patch",
        "-c",
        "--cl",
        "--changespec",
        dest="cl_name",
        required=True,
        help="NAME of the Patch whose DELTAS should be recomputed",
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

    # sase patch migrate-extension [--force] [--projects-dir DIR]
    migrate_parser = cs_subparsers.add_parser(
        "migrate-extension",
        help=(
            "Rename legacy .gp project spec files under ~/.sase/projects to "
            "the canonical .sase extension"
        ),
    )
    migrate_parser.set_defaults(changespec_subcommand="migrate-extension")
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


register_changespec_parser = register_patch_parser  # legacy parser alias


__all__ = [
    "register_changespec_parser",  # legacy parser alias
    "register_patch_parser",
]
