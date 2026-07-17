"""Argument parser definition for the ``sase artifact-file`` CLI subcommand."""

from __future__ import annotations

import argparse


_ARTIFACT_FILE_KINDS = ("chat", "plan", "image", "markdown", "pdf", "file")


def register_artifact_file_parser(subparsers: argparse._SubParsersAction) -> None:
    """Register the ``sase artifact-file`` subcommand parser."""
    artifact_file_parser = subparsers.add_parser(
        "artifact-file",
        help="Create and associate explicit agent artifact files",
    )
    artifact_file_subparsers = artifact_file_parser.add_subparsers(
        dest="artifact_file_subcommand",
        help="Artifact-file subcommands",
    )

    create_parser = artifact_file_subparsers.add_parser(
        "create",
        help="Move a file into SASE artifact-file storage for the current agent",
    )
    create_parser.add_argument(
        "-k",
        "--kind",
        choices=_ARTIFACT_FILE_KINDS,
        default=None,
        help="Artifact-file kind (default: infer from file extension)",
    )
    create_parser.add_argument(
        "-n",
        "--label",
        default=None,
        help="Display label for the artifact file (default: source file name)",
    )
    create_parser.add_argument(
        "-p",
        "--path",
        required=True,
        help="Source file to store as an artifact file",
    )
