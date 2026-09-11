"""Context-sensitive availability policy for top-level ACE actions."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from .tab_order import ARTIFACTS_TAB

CheckAction = Callable[[str, tuple[object, ...]], bool | None]

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
_AGENT_FLEET_ACTIONS = frozenset(
    {
        "connect_agent_machine",
        "setup_agent_machine",
        "retry_remote_agent",
        "view_remote_agent_content",
        "answer_remote_attention",
        "check_dispatch_launch_outcome",
    }
)
_LOCAL_AGENT_ROW_ACTIONS = frozenset(
    {
        "accept_proposal",
        "add_tag",
        "edit_agent_tribe",
        "edit_hooks",
        "edit_spec",
        "jump_to_agent_patch",
        "kill_agent",
        "open_artifact_files",
        "open_tmux",
        "rename_cl",
        "run_workflow",
        "show_agent_run_log",
        "start_agent_from_patch",
        "start_sibling_mode",
        "start_tmux_mode",
        "toggle_agent_unread",
        "toggle_attempt_view",
    }
)


def check_app_action(
    app: Any,
    action: str,
    parameters: tuple[object, ...],
    fallback: CheckAction,
) -> bool | None:
    """Return whether an app action is available in the current UI context."""
    if action == "start_agent_from_changespec":  # legacy compatibility alias
        action = "start_agent_from_patch"
    selected_agent = _selected_agent(app) if app.current_tab == "agents" else None
    selected_agent_remote = bool(
        selected_agent is not None
        and getattr(selected_agent, "fleet_origin_alias", None)
    )
    # A mounted prompt owns Enter/x and the rest of the Agents row map. The
    # underlying filtered list must not bulk-stop remote rows while the user
    # is typing or returning from the launch-target picker.
    if _prompt_input_owns_keys(app) and (
        action in _AGENT_FLEET_ACTIONS or action in _LOCAL_AGENT_ROW_ACTIONS
    ):
        return False
    if action in _AGENT_FLEET_ACTIONS:
        if app.current_tab != "agents":
            return False
        fleet_available = getattr(app, "_fleet_mode_available", None)
        if action == "connect_agent_machine":
            return selected_agent_remote
        if action == "setup_agent_machine":
            return not (bool(fleet_available()) if callable(fleet_available) else False)
        if action == "retry_remote_agent":
            return _remote_lifecycle_available(selected_agent, "lifecycle.retry")
        if action == "view_remote_agent_content":
            return _remote_content_available(selected_agent)
        if action == "answer_remote_attention":
            return _remote_attention_available(selected_agent)
        if action == "check_dispatch_launch_outcome":
            return bool(
                selected_agent_remote
                and getattr(selected_agent, "fleet_dispatch_operation_key", None)
            )
    if selected_agent_remote and action == "kill_agent":
        return _remote_lifecycle_available(selected_agent, "lifecycle.stop")
    if selected_agent_remote and action == "run_workflow":
        return _remote_lifecycle_available(selected_agent, "lifecycle.retry")
    if selected_agent_remote and action == "edit_hooks":
        return _remote_lifecycle_available(selected_agent, "lifecycle.fork")
    if selected_agent_remote and action == "edit_spec":
        marked = getattr(app, "_marked_agents", None)
        if marked:
            return True
        return _remote_content_available(selected_agent)
    if selected_agent_remote and action == "accept_proposal":
        return _remote_attention_available(selected_agent)
    if selected_agent_remote and action in _LOCAL_AGENT_ROW_ACTIONS:
        return False
    if action == "open_config_center" and getattr(
        app.screen, "_blocks_global_config_center_open", False
    ):
        # The active Admin Center owns its opener locally. On home that key
        # resumes the remembered section; on a working pane it must never push
        # a nested Admin Center over the current one.
        return False
    if action in (
        "next_tab",
        "prev_tab",
        "clear_marks",
    ):
        from textual.screen import ModalScreen

        if isinstance(app.screen, ModalScreen):
            return False
    if action in ("next_tab", "prev_tab"):
        from .widgets.vim_text_area import VimTextArea

        if isinstance(app.focused, VimTextArea):
            return False
    if action in {"search_forward", "search_reverse"}:
        from textual.screen import ModalScreen

        if (
            app.current_tab != "agents"
            or (
                bool(getattr(app, "_screen_stack", ()))
                and isinstance(app.screen, ModalScreen)
            )
            or (bool(getattr(app, "_screen_stack", ())) and app._prompt_input_active())
        ):
            return False
        if action == "search_reverse":
            metadata_search = getattr(app, "_agent_metadata_search", None)
            if not bool(getattr(metadata_search, "is_active", False)):
                return False
    # ``Ctrl+Space`` replays the last launched VCS xprompt by remounting the
    # prompt bar, which tears down whatever the user is currently typing
    # (``_show_prompt_input_bar_for_home`` unmounts first). The printable
    # launch keys (``+``, ``space``) are swallowed by the focused TextArea,
    # so this non-printable one is the only launch entry point that can reach
    # the app mid-prompt. Disable the action instead of the key so the guard
    # survives rebinding and covers every focus position inside the bar.
    if action == "start_agent_from_patch" and (
        bool(getattr(app, "_screen_stack", ())) and app._prompt_input_active()
    ):
        return False
    if action == "edit_query" and app.current_tab == "agents":
        return False
    if action == "add_axe_item":
        return app.current_tab == "axe"
    if action == "toggle_axe_description":
        return app.current_tab == "axe"
    if action == "toggle_attempt_view":
        return app.current_tab == "agents"
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
    if action in {"toggle_thinking", "toggle_thinking_reverse", "toggle_layout"}:
        if app.current_tab != "agents":
            return False
    if action in {
        "next_agent_metadata_section",
        "prev_agent_metadata_section",
    }:
        if app.current_tab != "agents":
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
    if action == "follow_artifact_link":
        available = getattr(app, "link_follow_available_for_selection", None)
        if callable(available):
            return bool(available())
        return bool(app.link_edges_for_selection())
    if action == "toggle_hide_reverted" and app.current_tab == ARTIFACTS_TAB:
        return False
    if action == "open_agent_cleanup_panel" and app.current_tab not in {
        "agents",
        "axe",
    }:
        return False
    if action == "save_marked_agents":
        if app.current_tab != "agents":
            return False
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
        app.current_tab == "axe"
        or (
            app.current_tab == ARTIFACTS_TAB
            and app.current_artifacts_pane_key != "patches"
        )
    ):
        return False
    return fallback(action, parameters)


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


def _prompt_input_owns_keys(app: Any) -> bool:
    """Return True while a prompt bar owns keyboard input."""
    prompt_active = getattr(app, "_prompt_input_active", None)
    return callable(prompt_active) and bool(prompt_active())


def _selected_agent(app: Any) -> Any:
    selected = getattr(app, "_get_selected_agent", None)
    if callable(selected):
        try:
            return selected()
        except Exception:
            return None
    return None


def _remote_lifecycle_available(agent: Any, capability: str) -> bool:
    from sase.ace.tui.actions.agents._remote_lifecycle import (
        is_remote_fleet_agent,
        remote_capability_enabled,
    )

    if agent is None:
        return False
    return is_remote_fleet_agent(agent) and remote_capability_enabled(agent, capability)


def _remote_attention_available(agent: Any) -> bool:
    from sase.ace.tui.actions.agents._remote_attention import (
        has_pending_remote_attention,
    )

    return bool(has_pending_remote_attention(agent))


def _remote_content_available(agent: Any) -> bool:
    from sase.ace.tui.actions.agents._remote_content import (
        remote_content_available,
    )

    return bool(remote_content_available(agent))
