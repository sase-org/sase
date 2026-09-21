"""Operation-context routing for bead CLI handlers."""

from __future__ import annotations

import sys
from collections.abc import Sequence
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from sase.bead.operation_context import BeadOperationContext


def resolve_bead_operation_context(
    targets: Sequence[str],
    *,
    for_write: bool = False,
    materialize: bool = False,
    require_single_store: bool = True,
    exit_on_error: bool = True,
) -> BeadOperationContext:
    """Resolve CLI bead targets or report a normal command error.

    This is the argparse/Python-handler counterpart to the Rust fast-path
    target extraction: callers pass only command operands that are bead IDs,
    never notes, titles, artifact refs, or file paths.
    """
    from sase.bead.operation_context import (
        BeadOperationRoutingError,
        resolve_operation_context_for_targets,
    )

    try:
        return resolve_operation_context_for_targets(
            targets,
            for_write=for_write,
            materialize=materialize,
            require_single_store=require_single_store,
        )
    except BeadOperationRoutingError as exc:
        message = _cli_routing_error_message(str(exc))
        if exit_on_error:
            print(f"Error: {message}", file=sys.stderr)
            sys.exit(1)
        raise RuntimeError(message) from exc


def _cli_routing_error_message(message: str) -> str:
    if message.startswith("Issue not found: "):
        return f"issue not found: {message.removeprefix('Issue not found: ')}"
    return message
