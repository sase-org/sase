"""Compatibility facade for ``sase bead work`` CLI helpers."""

from __future__ import annotations

from sase.bead import (
    cli_work_cleanup,
    cli_work_context,
    cli_work_handler,
    cli_work_launch,
    cli_work_plan,
)

BEAD_WORK_TIMING_ENV = cli_work_handler.BEAD_WORK_TIMING_ENV

confirm_launch = cli_work_plan.confirm_launch
expected_agent_names = cli_work_plan.expected_agent_names
find_live_name_collisions = cli_work_plan.find_live_name_collisions
handle_bead_work = cli_work_handler.handle_bead_work
print_work_plan_summary = cli_work_plan.print_work_plan_summary
resolve_changespec_launch_context = cli_work_context.resolve_changespec_launch_context
rollback_work_launch = cli_work_cleanup.rollback_work_launch

_launch_bead_work_agents = cli_work_launch.launch_bead_work_agents

__all__ = [
    "BEAD_WORK_TIMING_ENV",
    "_launch_bead_work_agents",
    "confirm_launch",
    "expected_agent_names",
    "find_live_name_collisions",
    "handle_bead_work",
    "print_work_plan_summary",
    "resolve_changespec_launch_context",
    "rollback_work_launch",
]
