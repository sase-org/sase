"""Argument parser definition for the top-level ``sase update`` command."""

from __future__ import annotations

import argparse


def register_update_parser(subparsers: argparse._SubParsersAction) -> None:
    """Register the ``sase update`` command parser."""
    update_parser = subparsers.add_parser(
        "update",
        help="Upgrade sase and all installed plugins together via uv",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        description=(
            "Upgrade sase and every installed sase plugin together, in one "
            "atomic operation, by delegating to `uv tool upgrade sase`. This "
            "re-resolves sase core and all injected plugins in a single shot, so "
            "they always move forward as a coherent set.\n"
            "\n"
            "This only works when sase was installed via `uv tool install sase` "
            "(the canonical install path). When run from a pip/pipx install or a "
            "dev checkout's virtualenv, it fails fast with an actionable message "
            "instead of touching your environment.\n"
            "\n"
            "Use `-n|--dry-run` to preview the exact uv command and the package "
            "set without changing anything. Use `-t|--to dev|pypi` to switch "
            "between editable development checkouts and published PyPI wheels. "
            "Switching to dev fast-forwards clean existing checkouts to their "
            "configured upstream before reinstalling editables."
        ),
        epilog=(
            "examples:\n"
            "  sase update            # upgrade sase + all plugins\n"
            "  sase update -n         # preview without changing anything\n"
            "  sase update -q         # only print a one-line summary\n"
            "  sase update -j         # stable machine-readable JSON\n"
            "  sase update -t dev     # switch to editable checkouts\n"
            "  sase update -t pypi -y # switch to published wheels without prompting\n"
            "\n"
            "Agent CLIs are separate; update them with `sase agent-cli update`."
        ),
    )
    # Options are listed short-alias alphabetical (-j, -n, -q, -t, -y) to match the bar
    # set by the `sase plugin install` / `sase plugin update` commands.
    update_parser.add_argument(
        "-j",
        "--json",
        action="store_true",
        help="Emit machine-readable JSON",
    )
    update_parser.add_argument(
        "-n",
        "--dry-run",
        action="store_true",
        help="Show the planned uv command and package set without running it",
    )
    update_parser.add_argument(
        "-q",
        "--quiet",
        action="store_true",
        help="Suppress progress output; print only a one-line summary",
    )
    update_parser.add_argument(
        "-t",
        "--to",
        choices=("dev", "pypi"),
        help="Switch install mode to editable checkouts or published PyPI wheels",
    )
    update_parser.add_argument(
        "-y",
        "--yes",
        action="store_true",
        help="Skip the install-mode switch confirmation prompt",
    )
