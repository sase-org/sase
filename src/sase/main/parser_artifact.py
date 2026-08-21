"""Argument parser definition for the ``sase artifact`` command group."""

from __future__ import annotations

import argparse

from sase.core.artifact_file_types import ARTIFACT_FILE_KINDS
from sase.main.parser_artifact_link import register_artifact_link_parser
from sase.main.parser_bead import nonnegative_int
from sase.main.plan_search_handler import plan_date_arg


def _positive_int(value: str) -> int:
    parsed = nonnegative_int(value)
    if parsed < 1:
        raise argparse.ArgumentTypeError("value must be at least 1")
    return parsed


def register_artifact_parser(subparsers: argparse._SubParsersAction) -> None:
    """Register canonical ``artifact`` and compatibility ``artifact-file``."""

    artifact_parser = subparsers.add_parser(
        "artifact",
        aliases=["artifact-file"],
        help="Create, discover, inspect, resolve, open, and repair artifacts",
        description=(
            "Create, discover, inspect, resolve, open, and repair indexed "
            "artifacts.\n\n"
            "Bare `sase artifact` defaults to `sase artifact list`. "
            "`sase artifact link` writes typed edges; `sase artifact read` "
            "prints an artifact and records the read. Canonical prompt "
            "archives live in the agents sidecar and are inspected with "
            "`sase agent prompts`."
        ),
        epilog=(
            "examples:\n"
            "  sase artifact\n"
            "  sase artifact list --kind image --project sase\n"
            "  sase artifact link add plan:a.md related plan:b.md "
            '"shares a root cause"\n'
            "  sase artifact link list plan:a.md\n"
            '  sase artifact read plan:a.md "Need the design of record"\n'
            "  sase artifact prune --keep-generations 3\n"
            "  sase artifact reclaim\n"
            "  sase artifact pane show stitches\n"
            "  sase artifact pane show ref:plan --json\n"
            "  sase artifact show file:explicit:0123456789abcdef01234567\n"
            "  sase artifact trash\n"
            "  sase artifact path plan:202607/example.md\n"
            "  sase agent prompts validate\n"
            "  sase artifact-file create --path report.md"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    artifact_subparsers = artifact_parser.add_subparsers(
        dest="artifact_subcommand",
        help="Artifact subcommands",
    )

    create_parser = artifact_subparsers.add_parser(
        "create",
        help="Store a file as an explicit artifact for the current agent",
    )
    create_parser.add_argument(
        "-b",
        "--bead",
        nargs="?",
        const="",
        default=None,
        metavar="ID",
        help=(
            "Attach the new file: reference to a bead "
            "(default when bare: the agent's SASE_BEAD_ID bead)"
        ),
    )
    create_parser.add_argument(
        "-k",
        "--kind",
        choices=ARTIFACT_FILE_KINDS,
        default=None,
        help="Artifact kind (default: infer from the file extension)",
    )
    create_parser.add_argument(
        "-l",
        "--label",
        default=None,
        help="Display label (default: source file name)",
    )
    create_parser.add_argument(
        "-m",
        "--move",
        action="store_true",
        help="Remove the source file after storing it (default: copy)",
    )
    create_parser.add_argument(
        "-p",
        "--path",
        required=True,
        help="Source file to copy into durable artifact storage",
    )

    doctor_parser = artifact_subparsers.add_parser(
        "doctor",
        help="Inspect, repair, and verify the artifact index",
        description=(
            "Inspect, repair, and verify the artifact index. Exits 1 when the\n"
            "index is unhealthy.\n\n"
            "Byte-free version-control-backed rows are healthy, not missing:\n"
            "  VCS reference rows          how many rows carry provenance\n"
            "                              instead of stored bytes\n"
            "  Incomplete VCS provenance   rows with a partial vcs_repo /\n"
            "                              vcs_sha / vcs_relpath triple\n"
            "  Unresolvable VCS references rows --verify could not\n"
            "                              materialize from any checkout\n\n"
            "Also reports dangling link rows, stale Links tables, missing\n"
            "companions, and rendered blocks whose links/ JSON is not in\n"
            "HEAD. --fix rebuilds the aggregate and projections from truth;\n"
            "it never parses Markdown for state."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    doctor_parser.add_argument(
        "-f",
        "--fix",
        action="store_true",
        help="Backfill missing enrichment fields before inspecting",
    )
    doctor_parser.add_argument(
        "-v",
        "--verify",
        action="store_true",
        help=(
            "Re-hash live stored files and materialize VCS-backed rows to "
            "verify recorded digests"
        ),
    )

    register_artifact_link_parser(artifact_subparsers)

    list_parser = artifact_subparsers.add_parser(
        "list",
        help="List indexed artifacts (pretty table by default, JSON with -j)",
    )
    list_parser.add_argument(
        "-a",
        "--agent",
        default=None,
        help="Only show artifacts associated with this agent name",
    )
    list_parser.add_argument(
        "-e",
        "--explicit",
        action="store_true",
        help="Only show explicitly created artifacts",
    )
    list_parser.add_argument(
        "-j",
        "--json",
        action="store_true",
        help="Emit a machine-readable JSON array (stable schema)",
    )
    list_parser.add_argument(
        "-k",
        "--kind",
        action="append",
        choices=ARTIFACT_FILE_KINDS,
        default=None,
        help="Only show this artifact kind (repeatable)",
    )
    list_parser.add_argument(
        "-l",
        "--limit",
        type=nonnegative_int,
        default=50,
        help="Maximum artifacts to return (default: 50; 0 means unlimited)",
    )
    list_parser.add_argument(
        "-p",
        "--project",
        default=None,
        help="Only show a project by display name, alias, or canonical key",
    )
    list_parser.add_argument(
        "-q",
        "--query",
        default=None,
        help="Case-insensitive substring filter over label and paths",
    )
    list_parser.add_argument(
        "-s",
        "--since",
        type=plan_date_arg,
        default=None,
        help="Only show artifacts created on or after DATE",
        metavar="DATE",
    )
    list_parser.add_argument(
        "-u",
        "--unused",
        action="store_true",
        help="Only show artifacts no agent has ever referenced",
    )

    open_parser = artifact_subparsers.add_parser(
        "open",
        help="Open a resolved artifact reference with an appropriate viewer",
    )
    open_parser.add_argument(
        "reference",
        help="Artifact reference or a bare default:/explicit: file id",
    )

    pane_parser = artifact_subparsers.add_parser(
        "pane",
        help="Inspect compiled Artifacts pane contracts and capabilities",
        description=(
            "Inspect compiled Artifacts pane contracts. Capabilities are "
            "derived from declared facts by named host rules.\n\n"
            "Unknown pane ids fail and list the configured ids. They never "
            "fall back to another pane."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    pane_subparsers = pane_parser.add_subparsers(
        dest="pane_subcommand",
        help="Pane subcommands",
    )
    pane_show_parser = pane_subparsers.add_parser(
        "show",
        help="Explain one pane's compiled contract and capability verdicts",
        description=(
            "Show the compiled Artifacts pane contract and every closed "
            "capability as ON or OFF with its named rule, declared fact, "
            "and suppression reason."
        ),
    )
    pane_show_parser.add_argument(
        "-j",
        "--json",
        action="store_true",
        help="Emit one machine-readable contract explanation",
    )
    pane_show_parser.add_argument(
        "pane_id",
        help="Configured Artifacts pane id (for example stitches or ref:plan)",
    )

    path_parser = artifact_subparsers.add_parser(
        "path",
        help="Print the absolute filesystem path for an artifact reference",
    )
    path_parser.add_argument(
        "reference",
        help="Artifact reference or a bare default:/explicit: file id",
    )

    prune_parser = artifact_subparsers.add_parser(
        "prune",
        help="Plan retention and optionally move selected rows to trash",
        description=(
            "Plan removal of old automatic artifact captures. This command is "
            "a dry run unless --apply is passed; explicit, referenced, and "
            "consumed artifacts and every label's newest generation are "
            "protected."
        ),
    )
    prune_parser.add_argument(
        "-a",
        "--apply",
        action="store_true",
        help="Move planned rows into restorable trash",
    )
    prune_parser.add_argument(
        "-b",
        "--before",
        type=plan_date_arg,
        default=None,
        metavar="DATE",
        help=(
            "Require selected rows to be older than DATE "
            "(YYYY-MM-DD, YYYY-MM, YYYYMM, or relative 14d / 3w / 2m)"
        ),
    )
    prune_parser.add_argument(
        "-g",
        "--keep-generations",
        type=nonnegative_int,
        default=None,
        metavar="N",
        help=(
            "Keep the newest N captures per label "
            "(default: artifacts.retention.keep_per_label)"
        ),
    )
    prune_parser.add_argument(
        "-j",
        "--json",
        action="store_true",
        help="Emit one machine-readable plan and execution envelope",
    )
    prune_parser.add_argument(
        "-k",
        "--kind",
        action="append",
        choices=ARTIFACT_FILE_KINDS,
        default=None,
        help="Require this artifact kind (repeatable)",
    )
    prune_parser.add_argument(
        "-l",
        "--limit",
        type=nonnegative_int,
        default=None,
        metavar="N",
        help="Maximum rows to select (0 means unlimited)",
    )
    prune_parser.add_argument(
        "-m",
        "--min-size",
        type=nonnegative_int,
        default=None,
        metavar="BYTES",
        help="Require at least this many stored bytes",
    )
    prune_parser.add_argument(
        "-p",
        "--project",
        default=None,
        help="Only prune a project by display name, alias, or canonical key",
    )

    read_parser = artifact_subparsers.add_parser(
        "read",
        help="Print an artifact after recording an audited read",
        description=(
            "Resolve an artifact reference, strip leading frontmatter and "
            "managed Links / Referenced By tables, print the body, and "
            "record an audited read.\n\n"
            "A non-empty reason is required (positional). Markdown prints "
            "to stdout; a TTY pages, a pipe stays raw. Images, PDFs, and "
            "video print a metadata card and point at `sase artifact open`. "
            "`stitch:` prints the show payload plus the commit subject.\n\n"
            "The read is refused if the audit row cannot be recorded. Inside "
            "a SASE agent run with an identity, a `read` graph edge is also "
            "stored. `show`, `path`, and `open` stay silent."
        ),
        epilog=(
            "examples:\n"
            "  sase artifact read plan:202608/artifact_link_graph.md "
            '"Need the CLI contract"\n'
            "  sase artifact read @research:202608/report.md "
            '"Skim the measurements" -n 80\n'
            "  sase artifact read file:explicit:0123456789abcdef01234567 "
            '"Inspect the diagram" -f json'
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    read_parser.add_argument(
        "reference",
        help="Artifact reference or a bare default:/explicit: file id",
    )
    read_parser.add_argument(
        "reason",
        help="Why this artifact is being read (required, non-empty)",
    )
    read_parser.add_argument(
        "-f",
        "--format",
        choices=("json", "markdown", "rich"),
        default="markdown",
        help="Output format (default: markdown)",
    )
    read_parser.add_argument(
        "-n",
        "--lines",
        type=_positive_int,
        default=None,
        metavar="LINES",
        help="Print only the first LINES of stripped text",
    )

    reclaim_parser = artifact_subparsers.add_parser(
        "reclaim",
        help="Replace stored automatic rows with verified VCS references",
        description=(
            "Find automatic artifact rows whose exact bytes are reproducible "
            "from durable remote-tracking history. This command is a dry run "
            "unless --apply is passed. Applied bytes move to restorable trash "
            "and consume disk space until that trash is purged. Explicit, "
            "referenced, and consumed artifacts are protected."
        ),
    )
    reclaim_parser.add_argument(
        "-a",
        "--apply",
        action="store_true",
        help="Write VCS-backed rows and move redundant stored bytes to trash",
    )
    reclaim_parser.add_argument(
        "-d",
        "--max-history-scan",
        type=_positive_int,
        default=100,
        metavar="N",
        help="Maximum durable commits to inspect per path (default: 100)",
    )
    reclaim_parser.add_argument(
        "-j",
        "--json",
        action="store_true",
        help="Emit one machine-readable plan and execution envelope",
    )
    reclaim_parser.add_argument(
        "-l",
        "--limit",
        type=nonnegative_int,
        default=None,
        metavar="N",
        help="Maximum verified rows to convert (0 means unlimited)",
    )
    reclaim_parser.add_argument(
        "-p",
        "--project",
        default=None,
        help="Only reclaim a project by display name, alias, or canonical key",
    )

    show_parser = artifact_subparsers.add_parser(
        "show",
        help="Show artifact metadata, resolution details, and consumption",
        description=(
            "Show artifact metadata, reference-resolution details, and the "
            "recorded consumption summary."
        ),
    )
    show_parser.add_argument(
        "-j",
        "--json",
        action="store_true",
        help="Emit one machine-readable resolution envelope",
    )
    show_parser.add_argument(
        "reference",
        help="Artifact reference or a bare default:/explicit: file id",
    )

    stats_parser = artifact_subparsers.add_parser(
        "stats",
        help="Report artifact-store economics and default retention selection",
        description=(
            "Report artifact-store economics, durable-reference and "
            "consumption protections, trash occupancy, and what the default "
            "retention policy would select. This command is read-only."
        ),
    )
    stats_parser.add_argument(
        "-j",
        "--json",
        action="store_true",
        help="Emit one machine-readable statistics envelope",
    )
    stats_parser.add_argument(
        "-p",
        "--project",
        default=None,
        help="Only report a project by display name, alias, or canonical key",
    )
    stats_parser.add_argument(
        "-t",
        "--top",
        type=nonnegative_int,
        default=10,
        metavar="N",
        help="Maximum agent groups to show (default: 10)",
    )

    trash_parser = artifact_subparsers.add_parser(
        "trash",
        help="List, permanently purge, or restore artifact trash",
        description=(
            "Manage restorable artifact trash. Bare `sase artifact trash` "
            "defaults to `sase artifact trash list`."
        ),
    )
    trash_subparsers = trash_parser.add_subparsers(
        dest="trash_subcommand",
        help="Trash subcommands",
    )

    trash_list_parser = trash_subparsers.add_parser(
        "list",
        help="List restorable trash entries",
    )
    trash_list_parser.add_argument(
        "-j",
        "--json",
        action="store_true",
        help="Emit one machine-readable trash listing",
    )
    trash_list_parser.add_argument(
        "-l",
        "--limit",
        type=nonnegative_int,
        default=50,
        metavar="N",
        help="Maximum entries to show (default: 50; 0 means unlimited)",
    )

    trash_purge_parser = trash_subparsers.add_parser(
        "purge",
        help="Permanently delete trash entries past the grace period",
        description=(
            "Permanently delete trash entries. This is the only irreversible "
            "artifact operation: purged entries cannot be restored. Without "
            "--all, only entries older than "
            "artifacts.retention.trash_grace_days are deleted."
        ),
    )
    trash_purge_parser.add_argument(
        "-a",
        "--all",
        action="store_true",
        help="Ignore the grace period and permanently delete every entry",
    )
    trash_purge_parser.add_argument(
        "-j",
        "--json",
        action="store_true",
        help="Emit one machine-readable purge result",
    )

    trash_restore_parser = trash_subparsers.add_parser(
        "restore",
        help="Restore one trash entry's payload and complete index row",
    )
    trash_restore_parser.add_argument(
        "-j",
        "--json",
        action="store_true",
        help="Emit one machine-readable restore result",
    )
    trash_restore_parser.add_argument(
        "reference",
        help="Trash entry id or file artifact reference",
    )


__all__ = ["register_artifact_parser"]
