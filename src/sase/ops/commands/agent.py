"""Noninteractive agent operation runners."""

from __future__ import annotations

import argparse
from collections.abc import Callable
from functools import partial
from typing import Any

from sase.ops.cli import add_operation_io_flags, load_request
from sase.ops.commands._agent_cleanup import (
    apply_cleanup_payload_for_result as _apply_cleanup_payload_for_result,
    run_persist_cleanup,
)
from sase.ops.commands._agent_directive import (
    persist_directive_from_payload as _persist_directive_from_payload,
    run_persist_directive,
)
from sase.ops.commands._agent_revert import (
    run_revert,
    serialize_bulk_revert_preview as serialize_bulk_revert_preview,
    serialize_revert_preview as serialize_revert_preview,
)
from sase.ops.commands.common import OperationCommandResult, run_and_finish
from sase.ops.names import (
    AGENT_CLEANUP,
    AGENT_DRAIN,
    AGENT_PERSIST_DIRECTIVE,
    AGENT_REVERT,
)


def add_agent_operation_parsers(subparsers: argparse._SubParsersAction) -> None:
    """Register focused noninteractive agent operation commands."""
    cleanup = subparsers.add_parser(
        "persist-cleanup",
        help="Persist kill, dismiss, or save cleanup from a private request sidecar",
        description=(
            "Apply one JSON-shaped agent cleanup persistence spec. Identities "
            "and cleanup-plan details come from the private request sidecar."
        ),
    )
    add_operation_io_flags(cleanup)

    persist = subparsers.add_parser(
        "persist-directive",
        help="Persist an agent directive update from a private request sidecar",
        description=(
            "Apply one JSON-shaped agent-directive persistence spec. The "
            "artifacts directory is positional; mutation details come from "
            "the private request sidecar."
        ),
    )
    persist.add_argument(
        "artifacts_dir",
        help="Agent artifacts directory that owns the directive files",
    )
    add_operation_io_flags(persist)

    revert = subparsers.add_parser(
        "revert",
        help="Execute a previously previewed agent commit revert",
        description=(
            "Revert an agent's commits using identifiers from the command "
            "line and optional SHA/workspace details from the request sidecar."
        ),
    )
    revert.add_argument("name", help="Agent name whose commits should be reverted")
    add_operation_io_flags(revert)


def handle_agent_operation(args: argparse.Namespace) -> int:
    """Dispatch one focused agent operation command."""
    sub = getattr(args, "agent_subcommand", None)
    if sub == "drain":
        return run_and_finish(
            operation=AGENT_DRAIN,
            body=lambda: _run_drain(args),
            args=args,
            print_message=False,
        )
    if sub == "persist-directive":
        return run_and_finish(
            operation=AGENT_PERSIST_DIRECTIVE,
            body=lambda: run_persist_directive(args),
            args=args,
        )
    if sub == "revert":
        return run_and_finish(
            operation=AGENT_REVERT,
            body=lambda: run_revert(args),
            args=args,
        )
    if sub == "persist-cleanup":
        return run_and_finish(
            operation=AGENT_CLEANUP,
            body=lambda: run_persist_cleanup(args),
            args=args,
        )
    return 2


def _run_drain(args: argparse.Namespace) -> OperationCommandResult:
    from sase.agents.cli_drain import run_agents_drain
    from sase.ops.commands._agent_drain_notify import (
        send_usage_limit_drain_notification,
        settle_drain_trigger_agent,
    )

    request = load_request(AGENT_DRAIN, args)
    trigger = dict(request.payload) if request.payload.get("notify") else None
    report_fn: Callable[[Any], None] | None = None
    if trigger is not None:
        settle_drain_trigger_agent(
            trigger.get("trigger_agent"),
            trigger_artifacts_dir=trigger.get("trigger_artifacts_dir"),
        )
        report_fn = partial(send_usage_limit_drain_notification, trigger)

    result = run_agents_drain(args, report_fn=report_fn)
    return OperationCommandResult(
        success=result.success,
        message=result.message,
        payload=result.payload,
        exit_code=result.exit_code,
    )


__all__ = ["add_agent_operation_parsers", "handle_agent_operation"]
