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

CleanupPreview = cli_work_cleanup.CleanupPreview
CleanupTarget = cli_work_cleanup.CleanupTarget
confirm_cleanup = cli_work_plan.confirm_cleanup
confirm_launch = cli_work_plan.confirm_launch
expected_agent_names = cli_work_plan.expected_agent_names
handle_bead_work = cli_work_handler.handle_bead_work
preview_bead_work_force_reuse = cli_work_cleanup.preview_bead_work_force_reuse
print_work_plan_summary = cli_work_plan.print_work_plan_summary
render_cleanup_preview = cli_work_plan.render_cleanup_preview
resolve_changespec_launch_context = cli_work_context.resolve_changespec_launch_context
rollback_work_launch = cli_work_cleanup.rollback_work_launch

_launch_bead_work_agents = cli_work_launch.launch_bead_work_agents

__all__ = [
    "BEAD_WORK_TIMING_ENV",
    "CleanupPreview",
    "CleanupTarget",
    "_launch_bead_work_agents",
    "confirm_cleanup",
    "confirm_launch",
    "expected_agent_names",
    "handle_bead_work",
    "preview_bead_work_force_reuse",
    "print_work_plan_summary",
    "render_cleanup_preview",
    "resolve_changespec_launch_context",
    "rollback_work_launch",
]
