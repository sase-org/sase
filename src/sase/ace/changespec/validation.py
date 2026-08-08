"""Legacy validation names backed by :mod:`sase.ace.patch.validation`."""

from sase.ace.patch.validation import (
    all_hooks_passed_for_entries,
    all_hooks_passed_for_stitches,
    count_agent_runners_global,
    count_all_runners_global,
    count_hook_runners_global,
    count_running_agents_global,
    count_running_hooks_global,
    get_current_and_proposal_entry_ids,
    get_current_and_proposal_stitch_ids,
    has_any_error_suffix,
    has_any_running_agent,
    has_any_running_process,
    has_any_status_suffix,
    is_parent_ready_for_mail,
)

__all__ = [
    "all_hooks_passed_for_entries",
    "all_hooks_passed_for_stitches",
    "count_agent_runners_global",
    "count_all_runners_global",
    "count_hook_runners_global",
    "count_running_agents_global",
    "count_running_hooks_global",
    "get_current_and_proposal_entry_ids",
    "get_current_and_proposal_stitch_ids",
    "has_any_error_suffix",
    "has_any_running_agent",
    "has_any_running_process",
    "has_any_status_suffix",
    "is_parent_ready_for_mail",
]
