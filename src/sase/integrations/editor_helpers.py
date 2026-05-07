"""Editor helper bridge operations."""

from __future__ import annotations

import argparse
import sys
from typing import TextIO

from .mobile_helpers import handle_mobile_helper_bridge


def handle_editor_helper_bridge(
    args: argparse.Namespace,
    *,
    stdin: TextIO = sys.stdin,
    stdout: TextIO = sys.stdout,
    stderr: TextIO = sys.stderr,
) -> int:
    """Run an editor-branded alias for stable helper bridge operations."""
    operation = getattr(args, "editor_helper_bridge_subcommand", None)
    mobile_args = argparse.Namespace(mobile_helper_bridge_subcommand=operation)
    return handle_mobile_helper_bridge(
        mobile_args,
        stdin=stdin,
        stdout=stdout,
        stderr=stderr,
    )
