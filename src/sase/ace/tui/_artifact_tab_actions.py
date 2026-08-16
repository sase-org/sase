"""Capability-to-action metadata for Artifacts pane help and conformance."""

from __future__ import annotations

from sase.ace.tui._artifact_tab_model import PaneCapability


# Host actions that implement one closed capability. Adapter-specific
# commands stay listed so the conformance harness can require a registered
# implementation without forcing a unified keymap this phase.
CAPABILITY_HOST_ACTIONS: dict[PaneCapability, tuple[str, ...]] = {
    PaneCapability.ENTRY_NAVIGATION: (
        "plans_next",
        "plans_prev",
        "beads_next",
        "beads_prev",
        "files_next",
        "files_prev",
        "stitches_next",
        "stitches_prev",
        "jump_to_entry",
    ),
    PaneCapability.ENTRY_OPEN: (
        "plans_view_selected",
        "beads_view_selected",
        "files_view_selected",
        "stitches_view_selected",
    ),
    PaneCapability.FILTER_SESSION: (
        "edit_query",
        "plans_filters",
        "beads_filters",
        "files_filters",
        "stitches_filters",
        "patches_filters",
    ),
    PaneCapability.REFRESH: (
        "plans_refresh",
        "beads_refresh",
        "files_refresh",
        "stitches_refresh",
    ),
    PaneCapability.PROJECT_SCOPE: ("pick_artifacts_project",),
    PaneCapability.STABLE_MARKS: ("toggle_mark", "clear_marks"),
    PaneCapability.DETAIL_SCROLL: ("scroll_detail_down", "scroll_detail_up"),
    PaneCapability.STABLE_REFERENCE_COPY: ("copy_reference",),
    PaneCapability.QUERY_HISTORY: ("edit_query",),
    PaneCapability.SAVED_QUERIES: ("start_saved_query_mode",),
    PaneCapability.VERSIONS: ("files_prev_version", "files_next_version"),
    PaneCapability.MUTATION: (
        "beads_create",
        "beads_close",
        "beads_cycle_status",
        "change_status",
    ),
    PaneCapability.PLAN_APPROVE: ("plans_approve",),
    PaneCapability.PLAN_REJECT: ("plans_reject",),
    PaneCapability.PLAN_OPEN_BEAD: ("plans_open_bead",),
    PaneCapability.RELATIONS: (),
    PaneCapability.GROUPING: (),
    PaneCapability.STATUS_COUNTERS: (),
    PaneCapability.SHELL: (),
}


def host_actions_for_capability(capability: PaneCapability) -> tuple[str, ...]:
    return CAPABILITY_HOST_ACTIONS.get(capability, ())


def registered_host_actions() -> frozenset[str]:
    return frozenset(
        action for actions in CAPABILITY_HOST_ACTIONS.values() for action in actions
    )


__all__ = [
    "CAPABILITY_HOST_ACTIONS",
    "host_actions_for_capability",
    "registered_host_actions",
]
