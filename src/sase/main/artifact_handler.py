"""Handler for the ``sase artifact`` CLI subcommand."""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path
from typing import NoReturn

from sase.core.agent_artifact_facade import store_explicit_agent_artifact


def handle_artifact_command(args: argparse.Namespace) -> NoReturn:
    """Dispatch ``sase artifact`` subcommands."""
    subcommand = getattr(args, "artifact_subcommand", None)
    if subcommand == "create":
        _handle_artifact_create(args)

    print("Usage: sase artifact {create}", file=sys.stderr)
    sys.exit(1)


def _handle_artifact_create(args: argparse.Namespace) -> NoReturn:
    """Move a source file into persistent SASE artifact storage."""
    if os.environ.get("SASE_AGENT") != "1":
        print(
            "Error: sase artifact create must be run from inside a SASE agent "
            "(SASE_AGENT=1 is required)",
            file=sys.stderr,
        )
        sys.exit(1)

    agent_artifacts_dir = os.environ.get("SASE_ARTIFACTS_DIR")
    if not agent_artifacts_dir:
        print(
            "Error: sase artifact create requires SASE_ARTIFACTS_DIR",
            file=sys.stderr,
        )
        sys.exit(1)

    source_path = Path(args.path).expanduser()
    if not source_path.is_file():
        print(f"Error: artifact source file not found: {source_path}", file=sys.stderr)
        sys.exit(1)

    try:
        artifact = store_explicit_agent_artifact(
            source_path,
            agent_artifacts_dir,
            label=args.label,
            kind=args.kind,
            move=True,
        )
    except Exception as exc:
        print(f"Error: failed to create artifact: {exc}", file=sys.stderr)
        sys.exit(1)

    print(f"id: {artifact.id}")
    print(f"path: {artifact.path}")
    sys.exit(0)
