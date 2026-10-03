"""Artifacts-pane availability guards for top-level ACE actions."""

from __future__ import annotations

from typing import Any

from .tab_order import ARTIFACTS_TAB, SERVICES_TAB

_ARTIFACT_RELATION_ACTIONS = frozenset(
    {
        "start_ancestor_mode",
        "start_child_mode",
        "start_sibling_mode",
        "toggle_relation_panel",
    }
)
_ARTIFACT_GROUP_FOLD_ACTIONS = frozenset(
    {
        "expand_or_layout",
        "hooks_or_collapse",
        "hooks_or_collapse_all",
        "expand_all_folds",
    }
)
_ARTIFACT_GROUP_CYCLE_ACTIONS = frozenset(
    {
        "cycle_grouping_mode",
        "cycle_grouping_mode_reverse",
    }
)
_ARTIFACT_QUERY_HISTORY_ACTIONS = frozenset({"prev_query", "next_query"})
_ARTIFACT_SAVED_QUERY_ACTIONS = frozenset(
    {"start_saved_query_mode", "open_saved_query_picker"}
)
_CONTRACT_GATED_ARTIFACT_ACTIONS = (
    _ARTIFACT_RELATION_ACTIONS
    | _ARTIFACT_GROUP_FOLD_ACTIONS
    | _ARTIFACT_GROUP_CYCLE_ACTIONS
    | _ARTIFACT_QUERY_HISTORY_ACTIONS
    | _ARTIFACT_SAVED_QUERY_ACTIONS
)


def _artifact_contract_action_available(app: Any, action: str) -> bool:
    """Return whether a contract-gated Artifacts action reaches this pane."""
    from .artifact_tabs import PaneCapability, artifacts_pane_contract

    pane_key = str(app.current_artifacts_pane_key)
    contract = getattr(app, "active_artifacts_contract", None)
    if contract is None or getattr(contract, "id", pane_key) != pane_key:
        contract = artifacts_pane_contract(pane_key)
    if contract is None:
        return False
    if action in _ARTIFACT_RELATION_ACTIONS:
        return contract.has(PaneCapability.RELATIONS)
    if action in _ARTIFACT_QUERY_HISTORY_ACTIONS:
        return contract.has(PaneCapability.QUERY_HISTORY)
    if action in _ARTIFACT_SAVED_QUERY_ACTIONS:
        return contract.has(PaneCapability.SAVED_QUERIES)
    if action == "expand_all_folds" and contract.is_plan_adapter():
        # Fold-snap on Plan panes lives on ``zL``, not the bare key.
        return False
    if action in _ARTIFACT_GROUP_FOLD_ACTIONS | _ARTIFACT_GROUP_CYCLE_ACTIONS:
        return contract.has(PaneCapability.GROUPING)
    return True


def check_artifacts_availability(
    app: Any,
    action: str,
    parameters: tuple[object, ...],
) -> bool | None:
    """Return Artifacts-pane availability, or None when undecided."""
    del parameters
    if action == "show_diff" and app.current_tab != ARTIFACTS_TAB:
        return False
    if action == "open_artifact_files" and app.current_tab != "agents":
        return False

    from .actions.artifacts import (
        AGENTS_ARTIFACT_ACTIONS,
        BEADS_ARTIFACT_ACTIONS,
        COMMITS_ARTIFACT_ACTIONS,
        FILES_ARTIFACT_ACTIONS,
        NON_PRS_ARTIFACT_ACTIONS,
        PLANS_ARTIFACT_ACTIONS,
    )

    if (
        app.current_tab == ARTIFACTS_TAB
        and app.current_artifacts_pane_key != "patches"
        and action in _CONTRACT_GATED_ARTIFACT_ACTIONS
        and not _artifact_contract_action_available(app, action)
    ):
        return False
    if (
        app.current_tab == ARTIFACTS_TAB
        and app.current_artifacts_pane_key != "patches"
        and action not in NON_PRS_ARTIFACT_ACTIONS
    ):
        return False
    if action in COMMITS_ARTIFACT_ACTIONS:
        return (
            app.current_tab == ARTIFACTS_TAB
            and app.current_artifacts_pane_key == "stitches"
        )
    if action in AGENTS_ARTIFACT_ACTIONS:
        return (
            app.current_tab == ARTIFACTS_TAB
            and app.current_artifacts_pane_key == "agents"
        )
    if action in {
        "cycle_artifacts_subtab",
        "cycle_artifacts_subtab_reverse",
        "cycle_artifacts_split",
        "cycle_artifacts_split_reverse",
        "cycle_artifacts_description",
    }:
        if app.current_tab != ARTIFACTS_TAB:
            return False
    if action in _ARTIFACT_QUERY_HISTORY_ACTIONS:
        if app.current_tab == "agents":
            from .models.agent_live_query_engine import agents_unified_query_enabled

            return agents_unified_query_enabled() and bool(
                getattr(app, "_agents_filter_session_open", False)
            )
        if app.current_tab != ARTIFACTS_TAB:
            return False
        if not _artifact_contract_action_available(app, action):
            return False
    if action == "agents_filters":
        if app.current_tab != "agents":
            return False
        from .models.agent_live_query_engine import agents_unified_query_enabled

        return agents_unified_query_enabled()
    if action in {"cycle_files_subtab", "cycle_files_subtab_reverse"}:
        return False
    if action in {
        "show_artifacts_patches",
        "show_artifacts_prs",
        "show_artifacts_stitches",
        "show_artifacts_bugs",
        "show_artifacts_beads",
        "show_artifacts_agents",
        "show_artifacts_files",
        "show_artifacts_digit",
    }:
        if app.current_tab != ARTIFACTS_TAB:
            return False
    if action == "open_saved_query_picker":
        if app.current_tab != ARTIFACTS_TAB:
            return False
        if (
            app.current_artifacts_pane_key != "patches"
            and not _artifact_contract_action_available(app, action)
        ):
            return False
    if action == "start_saved_query_mode" and app.current_tab != ARTIFACTS_TAB:
        return False
    if action == "patches_filters":
        if (
            app.current_tab != ARTIFACTS_TAB
            or app.current_artifacts_pane_key != "patches"
        ):
            return False
    if action in PLANS_ARTIFACT_ACTIONS:
        from .artifact_tabs import PaneCapability, artifacts_pane_contract

        contract = getattr(app, "active_artifacts_contract", None) or (
            artifacts_pane_contract(str(app.current_artifacts_pane_key))
        )
        if (
            app.current_tab != ARTIFACTS_TAB
            or contract is None
            or not contract.is_document_provider()
        ):
            return False
        required = {
            "plans_approve": PaneCapability.PLAN_APPROVE,
            "plans_reject": PaneCapability.PLAN_REJECT,
        }.get(action)
        if required is not None and not contract.has(required):
            return False
    if action in BEADS_ARTIFACT_ACTIONS:
        if (
            app.current_tab != ARTIFACTS_TAB
            or app.current_artifacts_pane_key != "beads"
        ):
            return False
    if action in FILES_ARTIFACT_ACTIONS:
        if (
            app.current_tab != ARTIFACTS_TAB
            or app.current_artifacts_pane_key != "files"
        ):
            return False
    if action == "pick_artifacts_project":
        from .artifact_tabs import PaneCapability, artifacts_pane_contract

        contract = getattr(app, "active_artifacts_contract", None) or (
            artifacts_pane_contract(str(app.current_artifacts_pane_key))
        )
        if (
            app.current_tab != ARTIFACTS_TAB
            or contract is None
            or not contract.has(PaneCapability.PROJECT_SCOPE)
        ):
            return False
    if action in {"artifacts_load_more", "artifacts_unload"}:
        if app.current_tab != ARTIFACTS_TAB:
            return False
        prompt_active = getattr(app, "_prompt_input_active", None)
        if callable(prompt_active) and prompt_active():
            return False
        from textual.screen import ModalScreen

        if isinstance(getattr(app, "screen", None), ModalScreen):
            return False
    if action == "artifacts_link_marked":
        if (
            app.current_tab != ARTIFACTS_TAB
            or app.current_artifacts_pane_key == "patches"
        ):
            return False
        from .artifact_tabs import PaneCapability, artifacts_pane_contract

        contract = getattr(app, "active_artifacts_contract", None) or (
            artifacts_pane_contract(str(app.current_artifacts_pane_key))
        )
        return (
            contract is not None
            and contract.has(PaneCapability.STABLE_MARKS)
            and contract.has(PaneCapability.STABLE_REFERENCE_COPY)
        )
    if action in {
        "change_status",
        "bulk_change_status",
        "mark_pr_origin",
        "patches_toggle_reverted",
    }:
        if (
            app.current_tab != ARTIFACTS_TAB
            or app.current_artifacts_pane_key != "patches"
        ):
            return False
    if action == "toggle_relation_panel" and app.current_tab != ARTIFACTS_TAB:
        return False
    if (
        action in {"start_ancestor_mode", "start_child_mode"}
        and app.current_tab == "agents"
    ):
        # The `<` / `>` tree modes share a Textual key identity with the deck
        # swap aliases and are no-ops on the Agents tab (no relation
        # contract), so they stay off and the swap actions win the key.
        return False
    if action == "follow_artifact_link":
        available = getattr(app, "link_follow_available_for_selection", None)
        if callable(available):
            return bool(available())
        return bool(app.link_edges_for_selection())
    if action == "toggle_hide_reverted" and app.current_tab != SERVICES_TAB:
        return False
    if action == "open_agent_cleanup_panel" and app.current_tab not in {
        "agents",
        SERVICES_TAB,
    }:
        return False
    if action == "save_marked_agents":
        if app.current_tab != "agents":
            return False
    # NOTE: zoom_panel stays dispatch-available in both flag states: with
    # decks on, Z is the in-place zoom; with the flag off it opens the
    # legacy modal. (Do not gate it with `return None`; dispatch treats
    # None as disabled and the action would never fire.)
    if (
        action
        in {
            "zoom_panel",
            "isolate_panels",
            "collapse_panel_folds",
            "collapse_all_panel_folds",
        }
        and app.current_tab != "agents"
    ):
        return False
    if action == "start_fold_mode" and (
        app.current_tab == SERVICES_TAB
        or (
            app.current_tab == ARTIFACTS_TAB
            and app.current_artifacts_pane_key != "patches"
        )
    ):
        return False
    return None
