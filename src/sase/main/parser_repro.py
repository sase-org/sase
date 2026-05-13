"""Argument parser definition for the ``sase repro`` CLI subcommand."""

from __future__ import annotations

import argparse


def register_repro_parser(subparsers: argparse._SubParsersAction) -> None:
    """Register the ``sase repro`` subcommand parser."""

    repro_parser = subparsers.add_parser(
        "repro",
        help="Capture and replay reproduction bundles",
    )
    repro_subparsers = repro_parser.add_subparsers(
        dest="repro_subcommand", help="Reproduction subcommands"
    )

    capture_parser = repro_subparsers.add_parser(
        "capture",
        help="Capture a reproduction bundle",
    )
    capture_subparsers = capture_parser.add_subparsers(
        dest="repro_capture_subcommand", help="Capture targets"
    )
    agents_tab_parser = capture_subparsers.add_parser(
        "agents-tab",
        help="Capture an Agents-tab reproduction bundle from filesystem state",
    )
    agents_tab_parser.add_argument(
        "--output",
        required=True,
        help="Directory where agents_tab_repro.json and artifacts are written",
    )
    agents_tab_parser.add_argument(
        "--commit-safe",
        dest="commit_safe",
        action="store_true",
        default=True,
        help="Redact local names and paths for a shareable bundle (default)",
    )
    agents_tab_parser.add_argument(
        "--no-commit-safe",
        dest="commit_safe",
        action="store_false",
        help="Keep unredacted local identifiers in the capture",
    )
    agents_tab_parser.add_argument(
        "--size",
        default="120x40",
        help="Terminal size label to store with the bundle, WIDTHxHEIGHT",
    )
    agents_tab_parser.add_argument(
        "--json",
        action="store_true",
        help="Emit a machine-readable JSON result",
    )

    replay_parser = repro_subparsers.add_parser(
        "replay",
        help="Replay a reproduction bundle through the headless TUI harness",
    )
    replay_parser.add_argument("path", help="Bundle JSON file or bundle directory")
    replay_parser.add_argument(
        "--assert-stable",
        action="store_true",
        help="Exit non-zero if replay invariants fail",
    )
    replay_parser.add_argument(
        "--json",
        action="store_true",
        help="Emit a machine-readable JSON verdict",
    )
    replay_parser.add_argument(
        "--write-artifacts",
        help="Directory where replay screen text and SVG artifacts are written",
    )
    replay_parser.add_argument(
        "--size",
        default="120x40",
        help="Headless terminal size for replay, WIDTHxHEIGHT",
    )
