"""Capability-to-action metadata for Artifacts pane help and conformance."""

from __future__ import annotations

from dataclasses import fields

from sase.ace.tui._artifact_tab_model import ArtifactsPaneContract, PaneCapability
from sase.ace.tui.keymaps.app_keymaps import AppKeymaps
from sase.ace.tui.keymaps.key_validation import is_unbound_key, split_key_alternatives


# Host actions that implement one closed capability. sase-m6.9 unified
# ``refresh``/``artifacts_copy_reference`` onto a single contract action per
# capability; entries still listed per-pane (e.g. ``plans_open_bead``) are
# adapter-specific because the underlying data/verb genuinely differs by
# pane, not because a unification is still pending.
CAPABILITY_HOST_ACTIONS: dict[PaneCapability, tuple[str, ...]] = {
    PaneCapability.ENTRY_NAVIGATION: (
        "next_patch",
        "prev_patch",
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
    PaneCapability.REFRESH: ("refresh",),
    PaneCapability.PROJECT_SCOPE: ("pick_artifacts_project",),
    PaneCapability.STABLE_MARKS: ("toggle_mark", "clear_marks"),
    PaneCapability.DETAIL_SCROLL: ("scroll_detail_down", "scroll_detail_up"),
    PaneCapability.STABLE_REFERENCE_COPY: ("artifacts_copy_reference",),
    PaneCapability.QUERY_HISTORY: ("edit_query", "prev_query", "next_query"),
    PaneCapability.SAVED_QUERIES: (
        "start_saved_query_mode",
        "open_saved_query_picker",
    ),
    PaneCapability.VERSIONS: ("files_prev_version", "files_next_version"),
    PaneCapability.MUTATION: (
        "agents_revive",
        "beads_create",
        "beads_close",
        "beads_cycle_status",
        "change_status",
    ),
    PaneCapability.PLAN_APPROVE: ("plans_approve",),
    PaneCapability.PLAN_REJECT: ("plans_reject",),
    PaneCapability.PLAN_OPEN_BEAD: ("plans_open_bead",),
    PaneCapability.RELATIONS: (
        "start_ancestor_mode",
        "start_child_mode",
        "start_sibling_mode",
        "toggle_relation_panel",
        "beads_open_plan",
        "plans_open_bead",
    ),
    PaneCapability.GROUPING: (
        "expand_or_layout",
        "hooks_or_collapse",
        "hooks_or_collapse_all",
        "expand_all_folds",
        "cycle_grouping_mode",
        "cycle_grouping_mode_reverse",
    ),
    PaneCapability.STATUS_COUNTERS: (),
    PaneCapability.SHELL: (),
}


def action_applies_to_contract(contract: ArtifactsPaneContract, action: str) -> bool:
    """Return whether *action* is the host verb this pane's contract names.

    Capability tables list every pane-specific alias for a verb. A Beads pane
    does not name ``plans_next``; a Plan pane does not name ``files_open_external``.
    """

    if action == "expand_all_folds" and contract.has(PaneCapability.PLAN_OPEN_BEAD):
        return False
    if action in {"next_patch", "prev_patch", "patches_filters", "change_status"}:
        return contract.id == "patches"
    if action.startswith("stitches_"):
        return contract.id == "stitches"
    if action.startswith("beads_"):
        return contract.id == "beads"
    if action.startswith("agents_"):
        return contract.id == "agents"
    if action.startswith("files_"):
        return contract.id == "files"
    if action in {"plans_approve", "plans_reject", "plans_open_bead"}:
        return contract.is_plan_adapter()
    if action.startswith("plans_"):
        return contract.is_document_provider()
    return True


def keymap_actions_by_key(app_km: AppKeymaps) -> dict[str, tuple[str, ...]]:
    """Invert app keymaps to ``{key: (action, ...)}`` for binding checks."""

    mapping: dict[str, list[str]] = {}
    for item in fields(app_km):
        key = getattr(app_km, item.name)
        if not isinstance(key, str) or is_unbound_key(key):
            continue
        for part in split_key_alternatives(key):
            mapping.setdefault(part, []).append(item.name)
    return {key: tuple(actions) for key, actions in mapping.items()}


__all__ = [
    "CAPABILITY_HOST_ACTIONS",
    "action_applies_to_contract",
    "keymap_actions_by_key",
]
