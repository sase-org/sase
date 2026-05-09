"""Editor helper bridge operations."""

from __future__ import annotations

import argparse
import json
import sys
from typing import TextIO

from ._editor_helper_snippets import snippet_catalog_response
from ._mobile_helper_common import (
    MobileHelperBridgeError as _MobileHelperBridgeError,
    read_request as _read_request,
)
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
    if operation == "snippet-catalog":
        try:
            request = _read_request(stdin)
            response = snippet_catalog_response(request)
        except (_MobileHelperBridgeError, ValueError, TypeError) as exc:
            print(f"editor helper bridge error: {exc}", file=stderr)
            return 2

        json.dump(response, stdout, separators=(",", ":"))
        stdout.write("\n")
        return 0

    mobile_args = argparse.Namespace(mobile_helper_bridge_subcommand=operation)
    return handle_mobile_helper_bridge(
        mobile_args,
        stdin=stdin,
        stdout=stdout,
        stderr=stderr,
    )
