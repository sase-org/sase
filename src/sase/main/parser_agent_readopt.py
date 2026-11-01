"""Argument parser for explicit staged-handoff recovery."""

from __future__ import annotations

import argparse


def register_agent_readopt_parser(agents_sub: argparse._SubParsersAction) -> None:
    """Register ``sase agent readopt``."""
    parser = agents_sub.add_parser(
        "readopt",
        help="Retry a held staged handoff after its obligations are satisfied",
        description=(
            "Retry recovery for one originating agent turn. Finalizer repair must "
            "be completed separately before re-adoption; this command never skips "
            "settlement, ownership, or identity checks."
        ),
        epilog=(
            "examples:\n"
            "  sase agent readopt 260101.worker\n"
            "  sase agent readopt review-session -j"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "-j",
        "--json",
        action="store_true",
        help="Emit a structured JSON result",
    )
    parser.add_argument(
        "agent",
        metavar="AGENT",
        help="Originating agent or session with exactly one staged turn",
    )
