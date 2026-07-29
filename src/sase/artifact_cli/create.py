"""Implementation of ``sase artifact create``."""

from __future__ import annotations

import argparse
import os
from pathlib import Path
import sys

from sase.core.artifact_file_facade import store_explicit_artifact_file


def handle_create(args: argparse.Namespace) -> int:
    """Move a source file into persistent SASE artifact storage."""

    if os.environ.get("SASE_AGENT") != "1":
        return _error(
            "sase artifact create must be run from inside a SASE agent "
            "(SASE_AGENT=1 is required)"
        )

    agent_artifacts_dir = os.environ.get("SASE_ARTIFACTS_DIR")
    if not agent_artifacts_dir:
        return _error("sase artifact create requires SASE_ARTIFACTS_DIR")

    source_path = Path(args.path).expanduser()
    if not source_path.is_file():
        return _error(f"artifact source not found: {source_path}")

    try:
        artifact_file = store_explicit_artifact_file(
            source_path,
            agent_artifacts_dir,
            label=args.label,
            kind=args.kind,
            move=True,
        )
    except Exception as exc:
        return _error(f"failed to create artifact: {exc}")

    print(f"id: {artifact_file.id}")
    print(f"path: {artifact_file.path}")
    print(f"ref: file:{artifact_file.id}")
    return 0


def _error(message: str) -> int:
    print(f"Error: {message}", file=sys.stderr)
    return 1


__all__ = ["handle_create"]
