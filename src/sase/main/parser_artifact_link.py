"""Argument parser for the nested ``sase artifact link`` command group."""

from __future__ import annotations

import argparse

from sase.main.parser_bead import nonnegative_int


def register_artifact_link_parser(
    artifact_subparsers: argparse._SubParsersAction,
) -> None:
    """Register ``sase artifact link`` with add/list/migrate-notes/relation/rm."""

    link_parser = artifact_subparsers.add_parser(
        "link",
        help="Add, list, and remove typed artifact links",
        description=(
            "Typed, bidirectional artifact links. Bare `sase artifact link` "
            "defaults to `sase artifact link list`.\n\n"
            "`add` always takes an explicit source ref, a closed-registry "
            "relation, a target ref, and a one-line why. `blocks` and "
            "`depends-on` error with a pointer to `sase bead dep`."
        ),
        epilog=(
            "examples:\n"
            "  sase artifact link\n"
            "  sase artifact link add plan:202608/a.md implements "
            'bead:sase-js "extends the ref contract this epic landed"\n'
            "  sase artifact link list plan:202608/a.md -d both\n"
            "  sase artifact link rm plan:202608/a.md bead:sase-js "
            "-R implements\n"
            "  sase artifact link migrate-notes\n"
            "  sase artifact link relation show implements"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    link_subparsers = link_parser.add_subparsers(
        dest="link_subcommand",
        help="Link subcommands",
    )

    add_parser = link_subparsers.add_parser(
        "add",
        help="Add or rewrite one typed artifact link",
        description=(
            "Add one typed link. Unchanged edges print `unchanged` and "
            "exit 0. Refs accept a leading `@`. The source ref is always "
            "required; do not default it to the current agent."
        ),
        epilog=(
            "examples:\n"
            "  sase artifact link add plan:a.md related plan:b.md "
            '"shares the ACE-TUI flake root cause"\n'
            "  sase artifact link add @plan:a.md supersedes @plan:b.md "
            '"replaced by the v2 design"'
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    add_parser.add_argument(
        "source_ref",
        metavar="SOURCE",
        help="Source artifact reference (leading @ is optional)",
    )
    add_parser.add_argument(
        "relation",
        metavar="RELATION",
        help=(
            "Closed-registry relation slug (related, supersedes, "
            "implements, derives-from)"
        ),
    )
    add_parser.add_argument(
        "target_ref",
        metavar="TARGET",
        help="Target artifact reference (leading @ is optional)",
    )
    add_parser.add_argument(
        "why",
        metavar="WHY",
        help="Single-line description, max 240 characters",
    )

    list_parser = link_subparsers.add_parser(
        "list",
        help="List artifact links (pretty table by default, JSON with -j)",
        description=(
            "List links. Without a ref, show the current project's recent "
            "links (default limit 50, newest first). With a ref, show that "
            "artifact's neighborhood."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    list_parser.add_argument(
        "reference",
        nargs="?",
        default=None,
        help="Optional artifact reference whose neighborhood to show",
    )
    list_parser.add_argument(
        "-d",
        "--direction",
        choices=("both", "in", "out"),
        default="both",
        help="Neighborhood direction (default: both)",
    )
    list_parser.add_argument(
        "-j",
        "--json",
        action="store_true",
        help="Emit a machine-readable JSON array (stable schema)",
    )
    list_parser.add_argument(
        "-l",
        "--limit",
        type=nonnegative_int,
        default=50,
        metavar="N",
        help="Maximum rows to return (default: 50; 0 means unlimited)",
    )
    list_parser.add_argument(
        "-o",
        "--origin",
        default=None,
        help="Only show this origin (manual, migrated, prompt_ref, read, derived)",
    )
    list_parser.add_argument(
        "-R",
        "--relation",
        default=None,
        help="Only show this relation slug",
    )

    migrate_parser = link_subparsers.add_parser(
        "migrate-notes",
        help="Dry-run RELATED: bead-note migration (apply writes bead events)",
        description=(
            "Scan bead notes matching `RELATED: <id> — <why>` and plan "
            "`related` edges with origin `migrated`. Dry-run by default. "
            "`--apply` writes bead events and appends `MIGRATED:` notes; "
            "that mutation path lands with the beads phase."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    migrate_parser.add_argument(
        "-a",
        "--apply",
        action="store_true",
        help="Write bead events and MIGRATED: notes",
    )
    migrate_parser.add_argument(
        "-j",
        "--json",
        action="store_true",
        help="Emit a machine-readable migration plan",
    )

    relation_parser = link_subparsers.add_parser(
        "relation",
        help="Read the closed relation registry",
        description=(
            "Read the closed-registry relation vocabulary: direction, worked "
            "examples, and recommended endpoint kinds. Bare `sase artifact "
            "link relation` defaults to `list`."
        ),
        epilog=(
            "examples:\n"
            "  sase artifact link relation list\n"
            "  sase artifact link relation show implements"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    relation_subparsers = relation_parser.add_subparsers(
        dest="relation_subcommand",
        help="Relation subcommands",
    )
    relation_list_parser = relation_subparsers.add_parser(
        "list",
        help="List every relation in the closed registry",
    )
    relation_list_parser.add_argument(
        "-j",
        "--json",
        action="store_true",
        help="Emit a machine-readable JSON array (stable schema)",
    )
    relation_show_parser = relation_subparsers.add_parser(
        "show",
        help="Show one relation's direction, worked examples, and recommended kinds",
    )
    relation_show_parser.add_argument(
        "slug",
        metavar="SLUG",
        help="Relation slug (related, supersedes, implements, derives-from, ...)",
    )
    relation_show_parser.add_argument(
        "-j",
        "--json",
        action="store_true",
        help="Emit a machine-readable JSON object (stable schema)",
    )

    rm_parser = link_subparsers.add_parser(
        "rm",
        help="Remove typed artifact links between a pair",
        description=(
            "Remove stored edges between two artifacts. Without -R/--relation, "
            "every edge between the pair is removed. Refs accept a leading `@`."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    rm_parser.add_argument(
        "source_ref",
        metavar="SOURCE",
        help="One endpoint of the pair (leading @ is optional)",
    )
    rm_parser.add_argument(
        "target_ref",
        metavar="TARGET",
        help="The other endpoint of the pair (leading @ is optional)",
    )
    rm_parser.add_argument(
        "-R",
        "--relation",
        default=None,
        help="Only remove this relation slug (default: every edge between the pair)",
    )


__all__ = ["register_artifact_link_parser"]
