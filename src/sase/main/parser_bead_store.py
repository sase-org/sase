"""Store and relationship parser definitions for bead subcommands."""

from __future__ import annotations

import argparse

from sase.main.parser_bead_common import nonnegative_int


def register_bead_dep_parser(
    subparsers: argparse._SubParsersAction,
) -> None:
    """Register ``sase bead dep``."""
    parser = subparsers.add_parser(
        "dep",
        help="Inspect and manage dependencies",
        description=(
            "Inspect and manage dependency edges. Invoking 'sase bead dep' "
            "without a subcommand delegates to 'sase bead dep list'."
        ),
    )
    dep_subparsers = parser.add_subparsers(dest="dep_action")
    add_parser = dep_subparsers.add_parser("add", help="Add a dependency")
    add_parser.add_argument(
        "issue", help="Full or shorthand issue that depends on another"
    )
    add_parser.add_argument(
        "depends_on", help="Full or shorthand issue being depended on"
    )
    list_parser = dep_subparsers.add_parser(
        "list",
        help="List dependency edges",
        description=(
            "List dependency edges with blocking state and recorded provenance. "
            "A scoped read includes every status by default; a store-wide read "
            "defaults to open, claimed, and in-progress beads."
        ),
    )
    list_parser.add_argument("id", nargs="?", help="Full or shorthand issue ID")
    list_parser.add_argument(
        "-c",
        "--color",
        choices=["always", "auto", "never"],
        default="auto",
        help="Color output: always, auto, or never (default: auto)",
    )
    list_parser.add_argument(
        "-d",
        "--direction",
        choices=["both", "in", "out"],
        default="both",
        help="Edges to show: both, in, or out (default: both)",
    )
    list_parser.add_argument(
        "-f",
        "--format",
        choices=["compact", "full", "json"],
        default="compact",
        help="Output format: compact, full, or json (default: compact)",
    )
    list_parser.add_argument(
        "-n",
        "--limit",
        type=nonnegative_int,
        default=0,
        help="Maximum beads to print; 0 means unlimited",
    )
    list_parser.add_argument(
        "-s",
        "--status",
        choices=["claimed", "closed", "in_progress", "open"],
        action="append",
        help="Filter by status (repeatable)",
    )
    rm_parser = dep_subparsers.add_parser("rm", help="Remove dependencies")
    rm_parser.add_argument(
        "issue", help="Full or shorthand issue that depends on others"
    )
    rm_parser.add_argument(
        "depends_on",
        metavar="depends_on",
        nargs="+",
        help="Full or shorthand issues no longer depended on",
    )
    tree_parser = dep_subparsers.add_parser(
        "tree",
        help="Walk the dependency graph as a tree",
        description=(
            "Walk dependencies, blockers, or both as a deterministic tree. "
            "A scoped tree includes every status by default; a store-wide tree "
            "defaults to open, claimed, and in-progress beads."
        ),
    )
    tree_parser.add_argument("id", nargs="?", help="Full or shorthand issue ID")
    tree_parser.add_argument(
        "-c",
        "--color",
        choices=["always", "auto", "never"],
        default="auto",
        help="Color output: always, auto, or never (default: auto)",
    )
    tree_parser.add_argument(
        "-d",
        "--direction",
        choices=["both", "in", "out"],
        default="out",
        help="Direction to walk: both, in, or out (default: out)",
    )
    tree_parser.add_argument(
        "-f",
        "--format",
        choices=["compact", "full", "json"],
        default="compact",
        help="Output format: compact, full, or json (default: compact)",
    )
    tree_parser.add_argument(
        "-L",
        "--levels",
        type=nonnegative_int,
        default=0,
        help="Maximum levels to descend; 0 means unlimited",
    )
    tree_parser.add_argument(
        "-s",
        "--status",
        choices=["claimed", "closed", "in_progress", "open"],
        action="append",
        help="Filter by status (repeatable)",
    )


def register_bead_doctor_parser(
    subparsers: argparse._SubParsersAction,
) -> None:
    """Register ``sase bead doctor``."""
    parser = subparsers.add_parser(
        "doctor",
        help="Validate bead-store health, design links, and artifact references",
    )
    parser.add_argument(
        "-F",
        "--fix-design-refs",
        action="store_true",
        help=(
            "Preview and, after confirmation, repair recoverable bead design references"
        ),
    )
    parser.add_argument(
        "-I",
        "--fix-issue-prefix",
        action="store_true",
        help=(
            "Preview and, after confirmation, reset the store's issue prefix "
            "to the project name"
        ),
    )
    parser.add_argument(
        "-P",
        "--fix-projection",
        action="store_true",
        help=(
            "Preview and, after confirmation, rewrite issues.jsonl from canonical events"
        ),
    )
    parser.add_argument(
        "-y",
        "--yes",
        action="store_true",
        help="Apply requested repairs without an interactive confirmation",
    )


def register_bead_init_parser(
    subparsers: argparse._SubParsersAction,
) -> None:
    """Register ``sase bead init``."""
    subparsers.add_parser("init", help="Create the effective SDD bead store")


def register_bead_pages_parser(
    subparsers: argparse._SubParsersAction,
) -> None:
    """Register ``sase bead pages``."""
    parser = subparsers.add_parser(
        "pages",
        help="Refresh generated bead pages or print a page URL",
        description=(
            "Reconcile generated Markdown pages in the project's beads "
            "sidecar or resolve one bead's hosted page URL. A bare "
            "'sase bead pages' invocation prints this help."
        ),
        epilog=(
            "Examples:\n"
            "  sase bead pages refresh\n"
            "  sase bead pages refresh --bead sase-ai.7\n"
            "  sase bead pages refresh --json\n"
            "  sase bead pages refresh --write\n"
            "  sase bead pages url sase-ai.7"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.set_defaults(_bead_pages_parser=parser)
    pages_subparsers = parser.add_subparsers(
        dest="pages_action",
        help="Page subcommands",
        metavar="<subcommand>",
        title="subcommands",
    )
    refresh_parser = pages_subparsers.add_parser(
        "refresh",
        help="Reconcile generated pages from durable bead state",
        description=(
            "Rebuild bead lineage pages from durable state and repository "
            "history. The default is a read-only dry run; --write applies "
            "changes, removes orphaned pages, and commits one beads-store batch."
        ),
        epilog=(
            "Examples:\n"
            "  sase bead pages refresh\n"
            "  sase bead pages refresh --bead sase-ai.7\n"
            "  sase bead pages refresh --json\n"
            "  sase bead pages refresh --write"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    refresh_parser.add_argument(
        "-b",
        "--bead",
        metavar="ID",
        help="Refresh only the lineage containing a full or shorthand bead ID",
    )
    refresh_parser.add_argument(
        "-j",
        "--json",
        action="store_true",
        help="Emit a machine-readable refresh report",
    )
    refresh_parser.add_argument(
        "-w",
        "--write",
        action="store_true",
        help="Write and commit changed pages (default: dry run)",
    )
    url_parser = pages_subparsers.add_parser(
        "url",
        help="Print one bead's hosted page URL",
        description=(
            "Resolve one bead's deterministic page address against the local "
            "beads-sidecar remote and branch. This command never uses the network."
        ),
    )
    url_parser.add_argument("bead_id", help="Full or shorthand bead ID")


def register_bead_ref_parser(
    subparsers: argparse._SubParsersAction,
) -> None:
    """Register ``sase bead ref``."""
    parser = subparsers.add_parser(
        "ref",
        help="Inspect and manage artifact references",
        description=(
            "Inspect and manage artifact references. Invoking 'sase bead ref' "
            "without a subcommand delegates to 'sase bead ref list'."
        ),
    )
    ref_subparsers = parser.add_subparsers(dest="ref_action")
    add_parser = ref_subparsers.add_parser("add", help="Attach artifact references")
    add_parser.add_argument("id", help="Full or shorthand issue ID")
    add_parser.add_argument("refs", nargs="+", help="Artifact references to attach")
    list_parser = ref_subparsers.add_parser("list", help="List artifact references")
    list_parser.add_argument("id", nargs="?", help="Full or shorthand issue ID")
    list_parser.add_argument(
        "-j",
        "--json",
        action="store_true",
        help="Emit machine-readable reference data",
    )
    list_parser.add_argument(
        "-r",
        "--resolve",
        action="store_true",
        help="Resolve references against the current workspace",
    )
    rm_parser = ref_subparsers.add_parser("rm", help="Detach artifact references")
    rm_parser.add_argument("id", help="Full or shorthand issue ID")
    rm_parser.add_argument("refs", nargs="+", help="Artifact references to detach")


def register_bead_resolve_conflicts_parser(
    subparsers: argparse._SubParsersAction,
) -> None:
    """Register ``sase bead resolve-conflicts``."""
    subparsers.add_parser(
        "resolve-conflicts",
        help="Resolve mechanical git conflicts in sdd/beads event streams",
        description=(
            "Resolve merge or rebase conflicts in generated bead state. "
            "Only sdd/beads/issues.jsonl, events/manifest.json, "
            "config.json (next_counter-only), and "
            "events/streams/*.jsonl conflicts are auto-merged."
        ),
    )


def register_bead_sync_parser(
    subparsers: argparse._SubParsersAction,
) -> None:
    """Register ``sase bead sync``."""
    parser = subparsers.add_parser("sync", help="Sync with git")
    parser.add_argument(
        "-s", "--status", action="store_true", help="Just check sync status"
    )


def register_bead_sync_external_parser(
    subparsers: argparse._SubParsersAction,
) -> None:
    """Register ``sase bead sync-external``."""
    parser = subparsers.add_parser(
        "sync-external",
        help="Mirror external tracker issues into task beads",
        description=(
            "Diff an enabled project's external tracker against its beads on "
            "external_ref and create small open task beads for uncovered "
            "issues. Upstream closes and reopens update mirrored beads when "
            "safe, while referenced, worked, parented, and already-matching "
            "beads get attributed notes only. Runs the same reconciliation "
            "pass as the external_issue_mirror AXE chop."
        ),
        epilog=(
            "Examples:\n"
            "  sase bead sync-external\n"
            "  sase bead sync-external --project sase --dry-run\n"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "-f",
        "--full",
        action="store_true",
        help="Force a full repair scan instead of the steady-state short-circuit",
    )
    parser.add_argument(
        "-n",
        "--dry-run",
        action="store_true",
        help="Show exact planned creations and status transitions without mutating anything",
    )
    parser.add_argument(
        "-p",
        "--project",
        default=None,
        help="Only mirror one project by display name, alias, or canonical key",
    )
