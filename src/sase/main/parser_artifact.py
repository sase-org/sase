"""Argument parser definition for the ``sase artifact`` CLI subcommand."""

from __future__ import annotations

import argparse


_ARTIFACT_KINDS = ("chat", "plan", "image", "markdown", "pdf", "file")


def register_artifact_parser(subparsers: argparse._SubParsersAction) -> None:
    """Register the ``sase artifact`` subcommand parser."""
    artifact_parser = subparsers.add_parser(
        "artifact",
        help="Create and associate explicit agent artifacts",
    )
    artifact_subparsers = artifact_parser.add_subparsers(
        dest="artifact_subcommand",
        help="Artifact subcommands",
    )

    create_parser = artifact_subparsers.add_parser(
        "create",
        help="Move a file into SASE artifact storage for the current agent",
    )
    create_parser.add_argument(
        "-p",
        "--path",
        required=True,
        help="Source file to store as an artifact",
    )
    create_parser.add_argument(
        "-n",
        "--label",
        default=None,
        help="Display label for the artifact (default: source file name)",
    )
    create_parser.add_argument(
        "-k",
        "--kind",
        choices=_ARTIFACT_KINDS,
        default=None,
        help="Artifact kind (default: infer from file extension)",
    )
