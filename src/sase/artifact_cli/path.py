"""Implementation of ``sase artifact path``."""

from __future__ import annotations

import argparse
from pathlib import Path
import sys

from sase.artifact_cli.references import (
    resolution_error_lines,
    resolve_cli_reference,
)


def handle_path(args: argparse.Namespace) -> int:
    """Print exactly one absolute path for a resolved filesystem reference."""

    try:
        result = resolve_cli_reference(args.reference)
    except (RuntimeError, ValueError) as exc:
        print(f"Error: malformed artifact reference: {exc}", file=sys.stderr)
        return 1

    if not result.is_filesystem_backed:
        print(
            f"Error: {result.parsed.kind}: references have no filesystem identity; "
            f"use `sase artifact show {result.canonical_reference}`",
            file=sys.stderr,
        )
        return 2
    if (
        result.resolution.status not in {"exact", "drifted"}
        or result.resolution.resolved_path is None
    ):
        for line in resolution_error_lines(result):
            print(line, file=sys.stderr)
        return 1

    path = Path(result.resolution.resolved_path).expanduser().resolve(strict=False)
    print(path)
    return 0


__all__ = ["handle_path"]
