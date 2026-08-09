"""Context-sensitive availability policy for top-level ACE actions."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from .tab_order import ARTIFACTS_TAB

CheckAction = Callable[[str, tuple[object, ...]], bool | None]


def check_app_action(
    app: Any,
    action: str,
    parameters: tuple[object, ...],
    fallback: CheckAction,
) -> bool | None:
    """Return whether an app action is available in the current UI context."""
    if action == "start_agent_from_changespec":
        action = "start_agent_from_patch"
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
        "activate_bug_link",
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
    # ``Ctrl+Space`` replays the last launch selection by remounting the
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
    if action == "edit_query" and (
        app.current_tab == "agents"
        or (app.current_tab == ARTIFACTS_TAB and app.current_artifacts_subtab == "bugs")
    ):
        return False
    if action == "add_axe_item":
        return app.current_tab == "axe"
    if action == "toggle_axe_description":
        return app.current_tab == "axe"
    if action == "show_diff" and app.current_tab != ARTIFACTS_TAB:
        return False
    if action == "open_artifact_files" and app.current_tab != "agents":
        return False

    from .actions.artifact_bugs import BUG_ARTIFACT_ACTIONS
    from .actions.artifacts import (
        BEADS_ARTIFACT_ACTIONS,
        CHATS_ARTIFACT_ACTIONS,
        COMMITS_ARTIFACT_ACTIONS,
        FILES_ARTIFACT_ACTIONS,
        NON_PRS_ARTIFACT_ACTIONS,
        PLANS_ARTIFACT_ACTIONS,
    )

    if (
        app.current_tab == ARTIFACTS_TAB
        and app.current_artifacts_pane_key != "prs"
        and action not in NON_PRS_ARTIFACT_ACTIONS
    ):
        return False
    if action in BUG_ARTIFACT_ACTIONS:
        return (
            app.current_tab == ARTIFACTS_TAB
            and app.current_artifacts_pane_key == "bugs"
        )
    if action in COMMITS_ARTIFACT_ACTIONS:
        return (
            app.current_tab == ARTIFACTS_TAB
            and app.current_artifacts_pane_key == "commits"
        )
    if (
        action == "refresh"
        and app.current_tab == ARTIFACTS_TAB
        and app.current_artifacts_pane_key in {"bugs", "commits", "other", "chats"}
    ):
        # ``y`` copies the selected pane entry; explicit pane refresh is
        # registry-backed and defaults to ``R``.
        return False
    if action in {
        "cycle_artifacts_subtab",
        "cycle_artifacts_subtab_reverse",
    }:
        if app.current_tab != ARTIFACTS_TAB:
            return False
    if action in {"cycle_files_subtab", "cycle_files_subtab_reverse"}:
        if app.current_tab != ARTIFACTS_TAB or app.current_artifacts_subtab != "files":
            return False
    if action in {
        "show_artifacts_prs",
        "show_artifacts_commits",
        "show_artifacts_bugs",
        "show_artifacts_beads",
        "show_artifacts_files",
    }:
        if app.current_tab != ARTIFACTS_TAB:
            return False
    if action == "open_saved_query_picker":
        if app.current_tab != ARTIFACTS_TAB or app.current_artifacts_subtab != "prs":
            return False
    if action == "start_saved_query_mode" and app.current_tab != ARTIFACTS_TAB:
        return False
    if action in PLANS_ARTIFACT_ACTIONS:
        if (
            app.current_tab != ARTIFACTS_TAB
            or app.current_artifacts_pane_key != "plans"
        ):
            return False
    if action in BEADS_ARTIFACT_ACTIONS:
        if (
            app.current_tab != ARTIFACTS_TAB
            or app.current_artifacts_pane_key != "beads"
        ):
            return False
    if action in CHATS_ARTIFACT_ACTIONS:
        if (
            app.current_tab != ARTIFACTS_TAB
            or app.current_artifacts_pane_key != "chats"
        ):
            return False
    if action in FILES_ARTIFACT_ACTIONS:
        if (
            app.current_tab != ARTIFACTS_TAB
            or app.current_artifacts_pane_key != "other"
        ):
            return False
    if action == "pick_artifacts_project":
        if app.current_tab != ARTIFACTS_TAB or app.current_artifacts_pane_key == "prs":
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
    if action in {"change_status", "bulk_change_status"}:
        if app.current_tab != ARTIFACTS_TAB:
            return False
    if action == "save_marked_agents":
        if app.current_tab != "agents":
            return False
    if action == "zoom_panel" and app.current_tab != "agents":
        return False
    if action == "start_fold_mode" and (
        app.current_tab == "axe"
        or (
            app.current_tab == ARTIFACTS_TAB and app.current_artifacts_pane_key != "prs"
        )
    ):
        return False
    return fallback(action, parameters)
