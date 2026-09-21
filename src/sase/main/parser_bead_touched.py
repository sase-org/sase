"""Argument parser for ``sase bead touched``."""

from __future__ import annotations

import argparse

from sase.bead.touch_glyphs import TOUCH_VERB_ORDER
from sase.main.parser_bead_common import nonnegative_int


def register_bead_touched_parser(
    subparsers: argparse._SubParsersAction,
) -> None:
    """Register ``sase bead touched``."""

    parser = subparsers.add_parser(
        "touched",
        help="List beads one agent touched",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        description=(
            "List the beads one agent touched, newest touch first, as recorded "
            "in the agent/bead touch index. One row per bead carries the bead "
            "id, the verb chips the agent performed on it with repeat counts, "
            "the bead's title, and the relative last-touch time. The index is "
            "a derived cache reduced from bead event streams, so a row "
            "reflects the last refresh, never a live stream scan; a missing "
            "index simply lists nothing. Counts report what the corpus "
            "contains, never what it wishes it contained. read comes from "
            "`sase bead read` / `sase artifact read bead:` with reasons, "
            "viewed comes from a machine-local log of human `show` views, "
            "so a remote agent's views are not visible while its mutations "
            "are, and automation never produces viewed. linked currently "
            "never appears: bead link events are owner-attributed and task "
            "sase-159 tracks that. The CLI lists touched beads only; the "
            "panel also marks assigned but untouched beads with an own chip."
        ),
        epilog=(
            "examples:\n"
            "  sase bead touched bbugyi200.athena.0oa\n"
            "  sase bead touched 0oa -l 10\n"
            "  sase bead touched 0oa -v noted -v closed\n"
            "  sase bead touched 0oa -v viewed\n"
            "  sase bead touched 0oa -v read -j\n"
            "\n"
            f"verbs: {', '.join(TOUCH_VERB_ORDER)}"
        ),
    )
    parser.add_argument(
        "agent",
        metavar="<agent>",
        help="Agent name to list touches for (globalized or local)",
    )
    parser.add_argument(
        "-j",
        "--json",
        action="store_true",
        help="Emit machine-readable JSON",
    )
    parser.add_argument(
        "-l",
        "--limit",
        type=nonnegative_int,
        default=None,
        metavar="N",
        help="Maximum beads to print; 0 means unlimited",
    )
    parser.add_argument(
        "-v",
        "--verb",
        action="append",
        default=None,
        metavar="VERB",
        help="Only show beads touched with this verb (repeatable)",
    )


__all__ = ["register_bead_touched_parser"]
