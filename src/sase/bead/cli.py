"""Compatibility facade for the 'sase bead' CLI handlers."""

from __future__ import annotations

from sase.bead import cli_basic, cli_common, cli_work
from sase.bead.cli_basic import (
    handle_bead_blocked,
    handle_bead_close,
    handle_bead_create,
    handle_bead_dep,
    handle_bead_doctor,
    handle_bead_init,
    handle_bead_list,
    handle_bead_onboard,
    handle_bead_ready,
    handle_bead_rm,
    handle_bead_show,
    handle_bead_stats,
    handle_bead_sync,
    handle_bead_update,
)
from sase.bead.cli_work import handle_bead_work
from sase.bead.model import IssueType, Status

_confirm_launch = cli_work.confirm_launch
_expected_agent_names = cli_work.expected_agent_names
_find_beads_location = cli_common.find_beads_location
_find_live_name_collisions = cli_work.find_live_name_collisions
_get_project = cli_common.get_project
_get_read_view = cli_common.get_read_view
_init_beads = cli_common.init_beads
_normalize_workspace_path = cli_common.normalize_workspace_path
_parse_type_arg = cli_basic._parse_type_arg
_print_work_plan_summary = cli_work.print_work_plan_summary
_resolve_changespec_launch_context = cli_work.resolve_changespec_launch_context
_rollback_work_launch = cli_work.rollback_work_launch
_status_icon = cli_common.status_icon

__all__ = [
    "IssueType",
    "Status",
    "_confirm_launch",
    "_expected_agent_names",
    "_find_beads_location",
    "_find_live_name_collisions",
    "_get_project",
    "_get_read_view",
    "_init_beads",
    "_normalize_workspace_path",
    "_parse_type_arg",
    "_print_work_plan_summary",
    "_resolve_changespec_launch_context",
    "_rollback_work_launch",
    "_status_icon",
    "handle_bead_blocked",
    "handle_bead_close",
    "handle_bead_create",
    "handle_bead_dep",
    "handle_bead_doctor",
    "handle_bead_init",
    "handle_bead_list",
    "handle_bead_onboard",
    "handle_bead_ready",
    "handle_bead_rm",
    "handle_bead_show",
    "handle_bead_stats",
    "handle_bead_sync",
    "handle_bead_update",
    "handle_bead_work",
]
