"""Handler for the ``sase artifact-file`` CLI subcommand."""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path
from typing import NoReturn

from sase.core.artifact_file_facade import store_explicit_artifact_file


def handle_artifact_file_command(args: argparse.Namespace) -> NoReturn:
    """Dispatch ``sase artifact-file`` subcommands."""
    subcommand = getattr(args, "artifact_file_subcommand", None)
    if subcommand == "create":
        _handle_artifact_file_create(args)

    print("Usage: sase artifact-file {create}", file=sys.stderr)
    sys.exit(1)


def _handle_artifact_file_create(args: argparse.Namespace) -> NoReturn:
    """Move a source file into persistent SASE artifact-file storage."""
    if os.environ.get("SASE_AGENT") != "1":
        print(
            "Error: sase artifact-file create must be run from inside a SASE agent "
            "(SASE_AGENT=1 is required)",
            file=sys.stderr,
        )
        sys.exit(1)

    agent_artifacts_dir = os.environ.get("SASE_ARTIFACTS_DIR")
    if not agent_artifacts_dir:
        print(
            "Error: sase artifact-file create requires SASE_ARTIFACTS_DIR",
            file=sys.stderr,
        )
        sys.exit(1)

    source_path = Path(args.path).expanduser()
    if not source_path.is_file():
        print(
            f"Error: artifact-file source not found: {source_path}",
            file=sys.stderr,
        )
        sys.exit(1)

    try:
        artifact_file = store_explicit_artifact_file(
            source_path,
            agent_artifacts_dir,
            label=args.label,
            kind=args.kind,
            move=True,
        )
    except Exception as exc:
        print(f"Error: failed to create artifact file: {exc}", file=sys.stderr)
        sys.exit(1)

    print(f"id: {artifact_file.id}")
    print(f"path: {artifact_file.path}")
    sys.exit(0)
