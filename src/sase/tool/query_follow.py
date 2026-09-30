"""``sase tool show --follow`` output streaming."""

from __future__ import annotations

import json
import sys
from typing import TYPE_CHECKING, Any

from sase.core.tool_run import tool_run_show
from sase.tool._query_shared import (
    detail_retention,
    output_truncation,
    print_show,
    show_triage,
)
from sase.tool.control import UnknownRunError
from sase.tool.follow_run import FollowOutcome, follow_run
from sase.tool.owner import owner_retention
from sase.tool.stage_protocol import attach_timeline

if TYPE_CHECKING:
    from sase.tool.query_show import ToolShowCliRequest


def handle_follow(request: ToolShowCliRequest, run_id: str) -> int:
    """Stream the output of record until the run settles, then summarize.

    Ctrl-C detaches the viewer and exits 130; the run continues.
    ``-F -j`` waits, then prints the final JSON envelope instead of the
    human summary. In an agent with a sync wait budget, following stops at
    the budget with the shared escalation block and exit 124.
    """

    try:
        first = tool_run_show(run_id)
    except Exception as exc:  # noqa: BLE001 - query failures are nonzero.
        print(str(exc), file=sys.stderr)
        return 1
    if not isinstance(first.get("run"), dict):
        diagnostic = "; ".join(str(item) for item in first.get("diagnostics") or ())
        print(diagnostic or f"tool run {run_id} was not found", file=sys.stderr)
        return 2
    budget: dict[str, Any] | None = None
    try:
        from sase.tool.routing import sync_wait_budget

        raw = sync_wait_budget()
        budget = dict(raw) if isinstance(raw, dict) else None
    except Exception:  # noqa: BLE001 - the budget never blocks a follow.
        budget = None
    deadline_s: float | None = None
    if budget is not None:
        try:
            deadline_s = float(budget["budget_seconds"])
        except (KeyError, TypeError, ValueError):
            deadline_s = None
            budget = None
    try:
        outcome: FollowOutcome = follow_run(run_id, deadline_s=deadline_s)
    except UnknownRunError as exc:
        print(str(exc), file=sys.stderr)
        return 2
    if outcome.kind == "stopped":
        print(
            "sase tool show: detached; the run continues",
            file=sys.stderr,
        )
        return 130
    if outcome.kind == "deadline":
        return _report_follow_budget(request, run_id, budget or {})
    final = outcome.envelope
    if final is None:  # No deadline is ever passed here; the loop ends settled.
        return 1
    run = final.get("run")
    if not isinstance(run, dict):
        print(f"tool run {run_id} was not found", file=sys.stderr)
        return 2
    attach_timeline(final)
    final["triage"] = show_triage(run_id)
    final["output_truncation"] = output_truncation(run)
    final["detail_retention"] = detail_retention(run)
    final["owner_retention"] = owner_retention(run)
    if request.json:
        print(json.dumps(final, indent=2, sort_keys=True))
        return 0
    print_show(final)
    for diagnostic in final.get("diagnostics") or ():
        print(str(diagnostic), file=sys.stderr)
    return 0


def _report_follow_budget(
    request: ToolShowCliRequest, run_id: str, budget: dict[str, Any]
) -> int:
    """Print the escalation block after a budget-bounded ``show -F``."""

    from sase.tool._control_shared import load_run
    from sase.tool.routing import escalation_block, escalation_json, is_joinable

    try:
        run = load_run(run_id)
    except UnknownRunError as exc:
        print(str(exc), file=sys.stderr)
        return 2
    joinable = is_joinable(run)
    block = escalation_block(run, budget, run_id)
    if request.json:
        try:
            envelope = tool_run_show(run_id)
        except Exception:  # noqa: BLE001 - fall back to the loaded run.
            envelope = {"run": run}
        if not isinstance(envelope, dict):
            envelope = {"run": run}
        envelope["escalation"] = escalation_json(
            run_id, budget, joinable, str(run.get("tool_name") or "") or None
        )
        print(json.dumps(envelope, indent=2, sort_keys=True))
        print(block, file=sys.stderr)
        return 124
    print(block, file=sys.stderr)
    return 124


__all__ = [
    "handle_follow",
]
