"""Argument parser definition for the ``sase footprint`` command group."""

from __future__ import annotations

import argparse

from sase.footprint.ids import NAMESPACES

_FORMAT_CHOICES = ("rich", "json", "markdown")

_FOOTPRINT_SUMMARY = "Show the local usage census of sase surfaces."
_FOOTPRINT_DESCRIPTION = (
    "Footprint keeps a local, privacy-by-construction census of which "
    "sase surfaces (CLI commands and options, TUI actions and keys, views "
    "and modals, macros, skills, config leaves, automation) are used, and "
    "joins it with a generated feature catalog. Use `sase footprint mode off` "
    "to stop recording. Bare `sase footprint` delegates to `list`."
)

_LENS_CHOICES = (
    "map",
    "cold",
    "fading",
    "agent-only",
    "dead-paths",
    "friction",
    "hot",
    "coverage",
    "decisions",
)

_ACTOR_CHOICES = ("you", "agents", "automation", "everyone")

_DECISION_CHOICES = ("keep", "later", "cut", "clear")

_REASON_CHOICES = (
    "rare_by_design",
    "safety",
    "agent_facing",
    "api_contract",
    "other",
)


def register_footprint_parser(subparsers: argparse._SubParsersAction) -> None:
    """Register the ``sase footprint`` group and its implemented views."""
    footprint_parser = subparsers.add_parser(
        "footprint",
        help=_FOOTPRINT_SUMMARY,
        description=_FOOTPRINT_DESCRIPTION,
    )
    footprint_sub = footprint_parser.add_subparsers(
        dest="footprint_subcommand",
        help="Footprint views",
        metavar="{backfill,catalog,clear,decide,list,mode,show,status}",
    )
    _register_backfill_parser(footprint_sub)
    _register_catalog_parser(footprint_sub)
    _register_clear_parser(footprint_sub)
    _register_decide_parser(footprint_sub)
    _register_list_parser(footprint_sub)
    _register_mode_parser(footprint_sub)
    _register_show_parser(footprint_sub)
    _register_status_parser(footprint_sub)


def _register_backfill_parser(
    footprint_sub: argparse._SubParsersAction,
) -> None:
    backfill_parser = footprint_sub.add_parser(
        "backfill",
        help="Import timestamped sase commands from zsh history",
        description=(
            "One-shot import of timestamped `sase` lines from zsh extended "
            "history into the local Footprint ledger. Only command and option "
            "IDs are kept. The file is never stored, the import is never "
            "automatic, and the history file still contains everything else "
            "you type. Re-running replaces the previous history origin."
        ),
        epilog=(
            "examples:\n"
            "  sase footprint backfill\n"
            "  sase footprint backfill -p ~/.zsh_history -y"
        ),
    )
    backfill_parser.add_argument(
        "-p",
        "--path",
        default=None,
        metavar="FILE",
        help="History file (default: $HISTFILE or ~/.zsh_history)",
    )
    backfill_parser.add_argument(
        "-y",
        "--yes",
        action="store_true",
        help="Import without asking for confirmation",
    )


def _register_mode_parser(footprint_sub: argparse._SubParsersAction) -> None:
    mode_parser = footprint_sub.add_parser(
        "mode",
        help="Show or set local Footprint recording",
        description=(
            "Show the effective Footprint recording mode, or set it to `off` "
            "or `local`. Recording is local and stores no command arguments."
        ),
    )
    mode_parser.add_argument(
        "mode",
        nargs="?",
        choices=("local", "off"),
        help="Recording mode (default: show the current mode)",
    )


def _register_catalog_parser(
    footprint_sub: argparse._SubParsersAction,
) -> None:
    catalog_parser = footprint_sub.add_parser(
        "catalog",
        help="List the generated feature catalog",
        description=(
            "List the generated Footprint feature catalog: every "
            "allowlisted feature ID sase knows, grouped by area. The file "
            "lives at src/sase/footprint/catalog.jsonl and is regenerated "
            "by `just fix`."
        ),
        epilog=(
            "examples:\n"
            "  sase footprint catalog\n"
            "  sase footprint catalog -n cli -f json\n"
            "  sase footprint catalog -A cli.bead -f markdown"
        ),
    )
    catalog_parser.add_argument(
        "-A",
        "--area",
        default=None,
        metavar="AREA",
        help="Show only one area (for example cli.bead)",
    )
    catalog_parser.add_argument(
        "-f",
        "--format",
        choices=_FORMAT_CHOICES,
        default="rich",
        help="Output format (default: rich)",
    )
    catalog_parser.add_argument(
        "-n",
        "--namespace",
        choices=NAMESPACES,
        default=None,
        metavar="NS",
        help="Show only one namespace (for example cli)",
    )


def _register_clear_parser(
    footprint_sub: argparse._SubParsersAction,
) -> None:
    clear_parser = footprint_sub.add_parser(
        "clear",
        help="Clear local Footprint data",
        description=(
            "Delete the local Footprint ledger and spool, then advance the "
            "generation so buffered TUI counts are discarded."
        ),
    )
    clear_parser.add_argument(
        "-y",
        "--yes",
        action="store_true",
        help="Clear without asking for confirmation",
    )


def _register_decide_parser(
    footprint_sub: argparse._SubParsersAction,
) -> None:
    decide_parser = footprint_sub.add_parser(
        "decide",
        help="Record a Footprint review decision",
        description=(
            "Record a local review decision for one feature ID: keep (with "
            "an optional keep reason), later (snooze 30 days), cut (mark for "
            "removal), or clear (delete the decision)."
        ),
        epilog=(
            "examples:\n"
            "  sase footprint decide cli:bead.list keep -r agent_facing\n"
            "  sase footprint decide cli:doctor.update cut"
        ),
    )
    decide_parser.add_argument(
        "feature_id",
        metavar="ID",
        help="Feature ID (for example cli:bead.list)",
    )
    decide_parser.add_argument(
        "decision",
        choices=_DECISION_CHOICES,
        help="Review decision",
    )
    decide_parser.add_argument(
        "-r",
        "--reason",
        choices=_REASON_CHOICES,
        default=None,
        help="Keep reason (default: none)",
    )


def _register_list_parser(
    footprint_sub: argparse._SubParsersAction,
) -> None:
    list_parser = footprint_sub.add_parser(
        "list",
        help="List Footprint features by lens",
        description=(
            "List Footprint features through one of nine lenses. Pending "
            "spool data is folded first when the last fold is more than ten "
            "minutes old."
        ),
        epilog=(
            "examples:\n"
            "  sase footprint list\n"
            "  sase footprint list -l cold -f markdown\n"
            "  sase footprint list -l hot -a everyone -r 90d"
        ),
    )
    list_parser.add_argument(
        "-a",
        "--actor",
        choices=_ACTOR_CHOICES,
        default="you",
        help="Actor scope (default: you)",
    )
    list_parser.add_argument(
        "-A",
        "--area",
        default=None,
        metavar="AREA",
        help="Show only one area (for example cli.bead)",
    )
    list_parser.add_argument(
        "-f",
        "--format",
        choices=_FORMAT_CHOICES,
        default="rich",
        help="Output format (default: rich)",
    )
    list_parser.add_argument(
        "-l",
        "--lens",
        choices=_LENS_CHOICES,
        default="map",
        help="Report lens (default: map)",
    )
    list_parser.add_argument(
        "-r",
        "--range",
        default="60d",
        metavar="RANGE",
        help="Window: Nd, Nw, or all (default: 60d)",
    )


def _register_show_parser(
    footprint_sub: argparse._SubParsersAction,
) -> None:
    show_parser = footprint_sub.add_parser(
        "show",
        help="Show one Footprint feature or area",
        description=(
            "Show the evidence card for one feature ID or area. Pending "
            "spool data is folded first when the last fold is more than ten "
            "minutes old."
        ),
        epilog=(
            "examples:\n"
            "  sase footprint show cli:bead.list\n"
            "  sase footprint show cli.bead -f markdown"
        ),
    )
    show_parser.add_argument(
        "feature_id",
        metavar="ID",
        help="Feature ID (for example cli:bead.list) or area (for example cli.bead)",
    )
    show_parser.add_argument(
        "-a",
        "--actor",
        choices=_ACTOR_CHOICES,
        default="you",
        help="Actor scope (default: you)",
    )
    show_parser.add_argument(
        "-f",
        "--format",
        choices=_FORMAT_CHOICES,
        default="rich",
        help="Output format (default: rich)",
    )
    show_parser.add_argument(
        "-r",
        "--range",
        default="60d",
        metavar="RANGE",
        help="Window: Nd, Nw, or all (default: 60d)",
    )


def _register_status_parser(
    footprint_sub: argparse._SubParsersAction,
) -> None:
    status_parser = footprint_sub.add_parser(
        "status",
        help="Show Footprint recording and ledger status",
        description=(
            "Show recording mode, ledger size, spool backlog, catalog, "
            "coverage, and fold faults. Pending spool data is folded first "
            "when the last fold is more than ten minutes old."
        ),
    )
    status_parser.add_argument(
        "-f",
        "--format",
        choices=("rich", "json"),
        default="rich",
        help="Output format (default: rich)",
    )


__all__ = ["register_footprint_parser"]
