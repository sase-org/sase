"""Handler for the ``sase plan reject`` CLI command."""

from __future__ import annotations

import argparse
import sys
from dataclasses import dataclass
from typing import TYPE_CHECKING, NoReturn

from sase.main.plan_pending import (
    ensure_plan_notification_available,
    plan_context_from_notification,
    resolve_pending_plan,
)
from sase.plan_approval_actions import (
    PlanApprovalActionError,
    PlanApprovalActionResult,
    execute_plan_approval_response,
)

if TYPE_CHECKING:
    from sase.ace.tui.actions.agents._plan_reject_cleanup import (
        PlanRejectionCleanupResult,
    )


@dataclass(frozen=True)
class _PlanRejectResult:
    """Combined response-write and durable-cleanup result for a rejection."""

    action_result: PlanApprovalActionResult
    cleanup: PlanRejectionCleanupResult


def handle_plan_reject_command(args: argparse.Namespace) -> NoReturn:
    """Reject one pending plan proposal from the CLI."""
    from rich.console import Console

    try:
        result = _reject_plan_from_cli(selector=getattr(args, "selector", None))
    except PlanApprovalActionError as exc:
        Console(stderr=True).print(f"[red]Error:[/red] {exc}")
        if exc.code in {"missing_selector", "ambiguous_prefix", "not_found"}:
            Console(stderr=True).print(
                "[dim]Run `sase plan list` to see pending plans.[/dim]"
            )
        sys.exit(2)

    action_result = result.action_result
    cleanup = result.cleanup
    Console().print(
        f"[green]{action_result.message}[/green] "
        f"[dim]{action_result.notification_id[:8]} -> {action_result.response_path}[/dim]"
    )
    if cleanup.warning:
        Console().print(f"[yellow]Warning:[/yellow] {cleanup.warning}")
    if cleanup.error:
        Console(stderr=True).print(
            f"[red]Plan rejected but agent cleanup failed:[/red] {cleanup.error}"
        )
        sys.exit(1)
    sys.exit(0)


def _reject_plan_from_cli(*, selector: str | None) -> _PlanRejectResult:
    """Resolve and reject a pending PlanApproval notification.

    Writes the runner ``{"action": "reject"}`` response first (the critical,
    agent-unblocking operation), then runs durable rejection side effects:
    user-kill the matching planner agent and hide its Agents-tab row through
    the same dismissed-agent persistence path the TUI uses.
    """
    from sase.ace.tui.actions.agents._plan_reject_cleanup import (
        perform_plan_rejection_cleanup,
    )

    notification = resolve_pending_plan(selector)
    ensure_plan_notification_available(notification)
    action_result = execute_plan_approval_response(
        plan_context_from_notification(notification),
        "reject",
    )
    cleanup = perform_plan_rejection_cleanup(notification)
    return _PlanRejectResult(action_result=action_result, cleanup=cleanup)
