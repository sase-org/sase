"""Agents, decks, and prompt guards for top-level ACE action availability."""

from __future__ import annotations

from typing import Any

from .tab_order import SERVICES_TAB

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
        "agents_retry",
        "start_tmux_mode",
        "toggle_agent_unread",
        "toggle_attempt_view",
        "view_agent_metadata",
    }
)
_DECK_NAV_ACTIONS = frozenset(
    {
        "next_deck_card",
        "prev_deck_card",
        "next_deck",
        "prev_deck",
        "pick_deck",
    }
)
_DECK_LAYOUT_ACTIONS = frozenset(
    {
        "toggle_deck_split_below",
        "toggle_deck_split_right",
        "toggle_deck_focus",
        "toggle_deck_focus_reverse",
        "swap_deck_panel_next",
        "swap_deck_panel_prev",
        "close_deck_panel",
        "turn_deck_layout",
        "grow_deck_panel",
        "shrink_deck_panel",
        "toggle_node_panel",
    }
)
_DECK_SPLIT_ONLY_ACTIONS = frozenset(
    {
        "toggle_deck_focus",
        "toggle_deck_focus_reverse",
        "swap_deck_panel_next",
        "swap_deck_panel_prev",
        "close_deck_panel",
        "turn_deck_layout",
        "grow_deck_panel",
        "shrink_deck_panel",
    }
)
_CARD_BLOCK_ACTIONS = frozenset(
    {
        "prev_card_block",
        "next_card_block",
    }
)
_DECK_VIEW_ACTIONS = frozenset(
    {
        "cycle_deck_view",
        "set_deck_view_at",
    }
)


def _focused_card_blocks_navigable(app: Any) -> bool:
    """Return the focused deck panel's cached card-block predicate."""
    try:
        from sase.ace.tui.widgets import AgentDetail

        detail = app.query_one("#agent-detail-panel", AgentDetail)
        panel = detail.deck_area.focused_panel()  # type: ignore[attr-defined]
        return bool(panel.card_blocks_navigable)
    except Exception:
        return False


def _focused_deck_view_cycle_available(app: Any) -> bool:
    """Return the focused deck panel's cached deck-view cycle predicate."""
    try:
        from sase.ace.tui.widgets import AgentDetail

        detail = app.query_one("#agent-detail-panel", AgentDetail)
        panel = detail.deck_area.focused_panel()  # type: ignore[attr-defined]
        return bool(panel.deck_view_cycle_available)
    except Exception:
        return False


def _deck_split_active(app: Any) -> bool:
    """Return whether a deck split layout is active."""
    try:
        from sase.ace.tui.widgets import AgentDetail
        from sase.ace.tui.widgets.decks.model import DeckLayout

        detail = app.query_one("#agent-detail-panel", AgentDetail)
        return detail.deck_layout is not DeckLayout.SINGLE  # type: ignore[attr-defined]
    except Exception:
        return False


def _prompt_input_owns_keys(app: Any) -> bool:
    """Return True while a prompt bar owns keyboard input."""
    prompt_active = getattr(app, "_prompt_input_active", None)
    if not callable(prompt_active):
        return False
    screen_stack = getattr(app, "_screen_stack", None)
    if screen_stack is not None and not bool(screen_stack):
        return False
    from textual.app import ScreenStackError

    try:
        return bool(prompt_active())
    except ScreenStackError:
        return False


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


def check_agents_availability(
    app: Any,
    action: str,
    parameters: tuple[object, ...],
) -> bool | None:
    """Return agents/decks/prompt availability, or None when undecided."""
    del parameters
    selected_agent = _selected_agent(app) if app.current_tab == "agents" else None
    selected_agent_remote = bool(
        selected_agent is not None
        and getattr(selected_agent, "fleet_origin_alias", None)
    )
    # A mounted prompt owns Enter/x and the rest of the Agents row map. The
    # underlying filtered list must not bulk-stop remote rows while the user
    # is typing or returning from the launch-target picker.
    if _prompt_input_owns_keys(app) and (
        action in _AGENT_FLEET_ACTIONS
        or action in _LOCAL_AGENT_ROW_ACTIONS
        or action in _DECK_NAV_ACTIONS
        or action in _DECK_LAYOUT_ACTIONS
        or action in _CARD_BLOCK_ACTIONS
        or action in _DECK_VIEW_ACTIONS
        or action == "act_on_agent"
    ):
        return False
    if action in _DECK_NAV_ACTIONS:
        if app.current_tab != "agents":
            return False
    if action in _CARD_BLOCK_ACTIONS:
        if app.current_tab != "agents":
            return False
        return bool(_focused_card_blocks_navigable(app))
    if action in _DECK_VIEW_ACTIONS:
        if app.current_tab != "agents":
            return False
        from textual.screen import ModalScreen

        if isinstance(getattr(app, "screen", None), ModalScreen):
            return False
        return bool(_focused_deck_view_cycle_available(app))
    if action in _DECK_LAYOUT_ACTIONS:
        if app.current_tab != "agents":
            return False
        if action in _DECK_SPLIT_ONLY_ACTIONS and not _deck_split_active(app):
            return False
    if action in {"scroll_prompt_down", "scroll_prompt_up"}:
        if app.current_tab == "agents":
            return False
    if action in {"next_chop_run", "prev_chop_run"}:
        return app.current_tab == "services"
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
    if action == "show_agent_run_log" and app.current_tab == "agents":
        return False
    if action == "view_agent_metadata":
        return (
            app.current_tab == "agents"
            and selected_agent is not None
            and not selected_agent_remote
        )
    if action == "agents_refresh":
        return app.current_tab == "agents"
    if action == "refresh" and app.current_tab == "agents":
        return False
    if action == "run_workflow" and app.current_tab == "agents":
        return False
    if action == "agents_retry" and app.current_tab != "agents":
        return False
    if action == "choose_agent_grouping":
        if app.current_tab != "agents" or _prompt_input_owns_keys(app):
            return False
        from textual.screen import ModalScreen

        if isinstance(getattr(app, "screen", None), ModalScreen):
            return False
    if action == "pick_deck":
        from textual.screen import ModalScreen

        if isinstance(getattr(app, "screen", None), ModalScreen):
            return False
    if action in {"cycle_grouping_mode", "cycle_grouping_mode_reverse"}:
        if app.current_tab == "agents":
            return False
    if selected_agent_remote and action == "kill_agent":
        return _remote_lifecycle_available(selected_agent, "lifecycle.stop")
    if selected_agent_remote and action == "agents_retry":
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
        # Focus can transiently leave the prompt's VimTextArea (deferred
        # refocus after a blur, mount-time deferred focus, frontmatter-panel
        # browse mode), so the guard must not depend on focus alone.
        if _prompt_input_owns_keys(app):
            return False
    if action in ("restore_prompt_stash", "quit", "stop_axe_and_quit"):
        # A typed ``@`` (for example in ``%m:@xlarge``) must never fire the
        # global stash restore while a prompt owns keys; stash access from an
        # open prompt remains available through the prompt-local ``Ctrl+G p``
        # and Ctrl+S-on-empty-pane paths. Likewise a stray ``q``/``Q``
        # during transient focus loss must not exit with a draft open. The
        # guard mirrors next_tab/prev_tab above and must not depend on focus
        # alone.
        if _prompt_input_owns_keys(app):
            return False
    if action == "search_reverse":
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
        metadata_search = getattr(app, "_agent_metadata_search", None)
        if not bool(getattr(metadata_search, "is_active", False)):
            return False
    # ``start_agent_from_patch`` replays the last launched VCS macro by
    # remounting the prompt bar, which tears down whatever the user is
    # currently typing (``_show_prompt_input_bar_for_home`` unmounts first).
    # The action is now bound to printable ``space``, which the focused
    # TextArea normally swallows (and the vim layer swallows unhandled
    # printable NORMAL keys), but the action-level guard still covers
    # rebinding to a non-printable key and every focus position inside
    # the bar.
    if action == "start_agent_from_patch" and (
        bool(getattr(app, "_screen_stack", ())) and app._prompt_input_active()
    ):
        return False
    if action == "add_axe_item":
        return app.current_tab == SERVICES_TAB
    if action == "toggle_axe_description":
        return app.current_tab == SERVICES_TAB
    if action == "toggle_attempt_view":
        return app.current_tab == "agents"
    if action == "toggle_agent_header":
        if app.current_tab != "agents" or _prompt_input_owns_keys(app):
            return False
        try:
            from .widgets import AgentDetail

            detail = app.query_one("#agent-detail-panel", AgentDetail)
        except Exception:
            return False
        # Unavailable while the header panel is hidden, so `d` stays a no-op
        # and the tab-gated `d` bindings on other tabs keep the key.
        try:
            return bool(detail.header_toggle_available())
        except Exception:
            return False
    if action == "toggle_agent_jump_panel":
        if app.current_tab != "agents" or _prompt_input_owns_keys(app):
            return False
        try:
            from .widgets import AgentDetail

            detail = app.query_one("#agent-detail-panel", AgentDetail)
        except Exception:
            return False
        # Unavailable until the panel phase adds the method and while the
        # jump panel is hidden, so `.` stays a no-op and the tab-gated `.`
        # bindings on other tabs keep the key.
        available = getattr(detail, "jump_panel_toggle_available", None)
        if not callable(available):
            return False
        try:
            return bool(available())
        except Exception:
            return False
    if action == "toggle_hide_non_run_agents" and app.current_tab != "agents":
        return False
    if action == "jump_to_node":
        if app.current_tab != "agents":
            return False
        if _prompt_input_owns_keys(app):
            return False
        from textual.screen import ModalScreen

        if isinstance(getattr(app, "screen", None), ModalScreen):
            return False
        if not bool(getattr(app, "_agents_first_load_done", False)):
            return False
        if bool(getattr(app, "_agents_filter_session_open", False)):
            return False
    if (
        action in {"focus_next_agent_panel", "focus_prev_agent_panel"}
        and app.current_tab != "agents"
    ):
        return False
    if action in {"next_agents_tab", "prev_agents_tab", "pick_agents_tab"}:
        # Agents tab only, not while the prompt input or a modal owns
        # keys. next/prev are additionally a no-op while the strip is
        # hidden; the picker needs at least two tabs to offer.
        if app.current_tab != "agents" or _prompt_input_owns_keys(app):
            return False
        from textual.screen import ModalScreen

        if isinstance(getattr(app, "screen", None), ModalScreen):
            return False
        try:
            from .actions.agents._agent_tabs import strip_visible_for_owner
        except Exception:
            return False
        return bool(strip_visible_for_owner(app))
    if (
        action in {"focus_next_service_panel", "focus_prev_service_panel"}
        and app.current_tab != SERVICES_TAB
    ):
        return False
    return None
