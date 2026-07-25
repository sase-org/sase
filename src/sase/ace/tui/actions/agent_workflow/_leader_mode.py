"""Leader mode handling for the ace TUI app."""

from __future__ import annotations

from typing import TYPE_CHECKING

from sase.agent.status_buckets import agent_is_asking

from ._types import TabName

if TYPE_CHECKING:
    from ....changespec import ChangeSpec
    from ...keymaps import KeymapRegistry
    from ...models import Agent


class LeaderModeMixin:
    """Mixin providing leader mode key handling and footer updates."""

    # Type hints for attributes accessed from AceApp (defined at runtime)
    changespecs: list[ChangeSpec]
    current_idx: int
    current_tab: TabName
    marked_indices: set[int]
    _agents: list[Agent]
    _leader_mode_active: bool
    _last_leader_key: str | None
    _keymap_registry: KeymapRegistry

    def action_start_leader_mode(self) -> None:
        """Enter leader mode for quick shortcuts (bound to ,)."""
        self._leader_mode_active = True
        self._update_leader_footer(current_tab=self.current_tab)

    def _handle_leader_key(self, key: str) -> bool:
        """Handle a key press in leader mode.

        Args:
            key: The key that was pressed.

        Returns:
            True if the key was handled, False otherwise.
        """
        # Always exit leader mode
        self._leader_mode_active = False

        if key == "escape":
            # Cancel silently and restore footer
            self._refresh_current_tab()  # type: ignore[attr-defined]
            return True

        leader_keys = self._keymap_registry.leader_mode.keys
        if key == leader_keys["repeat_last"]:
            if self._last_leader_key is None:
                self.notify("No leader command to repeat")  # type: ignore[attr-defined]
                self._refresh_current_tab()  # type: ignore[attr-defined]
                return True
            return LeaderModeMixin._dispatch_leader_key(
                self, self._last_leader_key, remember=False
            )

        return LeaderModeMixin._dispatch_leader_key(self, key, remember=True)

    def _remember_leader_key(self, key: str, *, remember: bool) -> None:
        """Remember a matched raw leader subkey for future repeat dispatch."""
        if remember:
            self._last_leader_key = key

    def _dispatch_leader_key(self, key: str, *, remember: bool) -> bool:
        """Dispatch a non-repeat leader subkey."""
        leader_keys = self._keymap_registry.leader_mode.keys

        if key == leader_keys["edit_query"]:
            if self.current_tab != "agents":
                self._refresh_current_tab()  # type: ignore[attr-defined]
                return True
            LeaderModeMixin._remember_leader_key(self, key, remember=remember)
            self.action_edit_query()  # type: ignore[attr-defined]
            self._refresh_current_tab()  # type: ignore[attr-defined]
            return True

        if key == leader_keys["show_help"]:
            LeaderModeMixin._remember_leader_key(self, key, remember=remember)
            self.action_show_help()  # type: ignore[attr-defined]
            self._refresh_current_tab()  # type: ignore[attr-defined]
            return True

        if key == leader_keys["run_cmd"]:
            LeaderModeMixin._remember_leader_key(self, key, remember=remember)
            if self.current_tab != "changespecs":
                self._refresh_current_tab()  # type: ignore[attr-defined]
                return True
            self._start_bgcmd_from_changespec()  # type: ignore[attr-defined]
            self._refresh_current_tab()  # type: ignore[attr-defined]
            return True

        if key == leader_keys["runners"]:
            LeaderModeMixin._remember_leader_key(self, key, remember=remember)
            self.action_show_runners()  # type: ignore[attr-defined]
            self._refresh_current_tab()  # type: ignore[attr-defined]
            return True

        if key == leader_keys["revert_agent"]:
            LeaderModeMixin._remember_leader_key(self, key, remember=remember)
            if self.current_tab == "agents":
                self._start_revert_selected_agent()  # type: ignore[attr-defined]
            self._refresh_current_tab()  # type: ignore[attr-defined]
            return True

        if key == leader_keys["kill_mentors"]:
            LeaderModeMixin._remember_leader_key(self, key, remember=remember)
            if self.current_tab == "changespecs":
                self.action_kill_mentors()  # type: ignore[attr-defined]
            self._refresh_current_tab()  # type: ignore[attr-defined]
            return True

        if key == leader_keys["review_mentors"]:
            LeaderModeMixin._remember_leader_key(self, key, remember=remember)
            if self.current_tab == "changespecs":
                self._open_mentor_review()  # type: ignore[attr-defined]
            self._refresh_current_tab()  # type: ignore[attr-defined]
            return True

        if key == leader_keys["agent_home"]:
            LeaderModeMixin._remember_leader_key(self, key, remember=remember)
            # Shortcut for @ → ~ (home): skip the ProjectSelectModal
            self._show_prompt_input_bar_for_home()  # type: ignore[attr-defined]
            self._refresh_current_tab()  # type: ignore[attr-defined]
            return True

        if key == leader_keys["agent_from_cl"]:
            LeaderModeMixin._remember_leader_key(self, key, remember=remember)
            if self.current_tab == "changespecs":
                if self.marked_indices:
                    self._start_agents_from_marked()  # type: ignore[attr-defined]
                else:
                    self._start_agent_from_changespec_quick()  # type: ignore[attr-defined]
            elif self.current_tab == "agents":
                self._start_agent_from_agent_quick()  # type: ignore[attr-defined]
            self._refresh_current_tab()  # type: ignore[attr-defined]
            return True

        if key == leader_keys["toggle_agent_panel_grouping"]:
            LeaderModeMixin._remember_leader_key(self, key, remember=remember)
            if self.current_tab == "agents":
                self.action_toggle_agent_panel_grouping()  # type: ignore[attr-defined]
            self._refresh_current_tab()  # type: ignore[attr-defined]
            return True

        if key == leader_keys["jump_to_next_unread_done_agent"]:
            LeaderModeMixin._remember_leader_key(self, key, remember=remember)
            if self.current_tab == "agents":
                if not self._jump_to_next_unread_done_agent():  # type: ignore[attr-defined]
                    self.notify("No unread completed agents")  # type: ignore[attr-defined]
            self._refresh_current_tab()  # type: ignore[attr-defined]
            return True

        if key == leader_keys["jump_to_next_stopped_agent"]:
            LeaderModeMixin._remember_leader_key(self, key, remember=remember)
            if self.current_tab == "agents":
                if not self._jump_to_next_stopped_agent():  # type: ignore[attr-defined]
                    self.notify("No stopped agents")  # type: ignore[attr-defined]
            self._refresh_current_tab()  # type: ignore[attr-defined]
            return True

        if key == leader_keys["full_history_refresh"]:
            LeaderModeMixin._remember_leader_key(self, key, remember=remember)
            if self.current_tab == "agents":
                self.action_refresh_agents_full_history()  # type: ignore[attr-defined]
            self._refresh_current_tab()  # type: ignore[attr-defined]
            return True

        if key == leader_keys["mark_all_unread_done_agents_read"]:
            LeaderModeMixin._remember_leader_key(self, key, remember=remember)
            if self.current_tab == "agents":
                marked_count = self._mark_all_unread_done_agents_read()  # type: ignore[attr-defined]
                if marked_count:
                    self.notify(  # type: ignore[attr-defined]
                        f"Marked {marked_count} completed agents read"
                    )
                else:
                    self.notify("No unread completed agents")  # type: ignore[attr-defined]
                    self._refresh_current_tab()  # type: ignore[attr-defined]
                return True
            self._refresh_current_tab()  # type: ignore[attr-defined]
            return True

        if key == leader_keys["kill_and_edit"]:
            LeaderModeMixin._remember_leader_key(self, key, remember=remember)
            if self.current_tab == "agents":
                # Marks take precedence: when any agent is marked, ,x operates on
                # the marked set; otherwise it acts on the focused row.  The raw
                # ``x`` subkey is remembered, so a repeat re-evaluates marks.
                if getattr(self, "_marked_agents", None):
                    self._bulk_kill_marked_agents_and_edit()  # type: ignore[attr-defined]
                else:
                    self._kill_and_edit_agent()  # type: ignore[attr-defined]
            self._refresh_current_tab()  # type: ignore[attr-defined]
            return True

        if key == leader_keys["clear_comments"]:
            LeaderModeMixin._remember_leader_key(self, key, remember=remember)
            if self.current_tab == "changespecs":
                self._clear_changespec_comments()  # type: ignore[attr-defined]
            self._refresh_current_tab()  # type: ignore[attr-defined]
            return True

        if key == leader_keys["open_prompt_stash"]:
            LeaderModeMixin._remember_leader_key(self, key, remember=remember)
            # Intentional pump ordering: this async action contains no await;
            # it only spawns its disk-reading coroutine as a retained task.
            self.call_later(self.action_open_prompt_stash)  # type: ignore[attr-defined]
            self._refresh_current_tab()  # type: ignore[attr-defined]
            return True

        if key == leader_keys["jump_to_notification"]:
            LeaderModeMixin._remember_leader_key(self, key, remember=remember)
            if self.current_tab == "agents":
                self._jump_to_agent_notification()  # type: ignore[attr-defined]
            self._refresh_current_tab()  # type: ignore[attr-defined]
            return True

        if key == leader_keys["capture_agents_repro"]:
            LeaderModeMixin._remember_leader_key(self, key, remember=remember)
            if self.current_tab == "agents":
                self.action_capture_agents_repro()  # type: ignore[attr-defined]
            self._refresh_current_tab()  # type: ignore[attr-defined]
            return True

        if key == leader_keys["toggle_agents_repro_checks"]:
            LeaderModeMixin._remember_leader_key(self, key, remember=remember)
            if self.current_tab == "agents":
                self.action_toggle_agents_repro_checks()  # type: ignore[attr-defined]
            self._refresh_current_tab()  # type: ignore[attr-defined]
            return True

        if key == leader_keys["prompt_history"]:
            LeaderModeMixin._remember_leader_key(self, key, remember=remember)
            self._start_prompt_history_from_last_selection()  # type: ignore[attr-defined]
            self._refresh_current_tab()  # type: ignore[attr-defined]
            return True

        if key == leader_keys["prompt_history_edit_first"]:
            LeaderModeMixin._remember_leader_key(self, key, remember=remember)
            self._start_prompt_history_from_last_selection(edit_first=True)  # type: ignore[attr-defined]
            self._refresh_current_tab()  # type: ignore[attr-defined]
            return True

        if key == leader_keys["prompt_history_cancelled"]:
            LeaderModeMixin._remember_leader_key(self, key, remember=remember)
            self._start_prompt_history_from_last_selection(show_cancelled=True)  # type: ignore[attr-defined]
            self._refresh_current_tab()  # type: ignore[attr-defined]
            return True

        if key == leader_keys["agent_run_log"]:
            LeaderModeMixin._remember_leader_key(self, key, remember=remember)
            if self.current_tab == "changespecs":
                self.action_show_agent_run_log()  # type: ignore[attr-defined]
            self._refresh_current_tab()  # type: ignore[attr-defined]
            return True

        # ``models_panel`` (leader ``,m``) replaced the old
        # ``temporary_llm_override`` action; accept the legacy key too so a
        # user keymap override referencing the old action id keeps working.
        if key == leader_keys.get("models_panel") or key == leader_keys.get(
            "temporary_llm_override"
        ):
            LeaderModeMixin._remember_leader_key(self, key, remember=remember)
            self._open_models_panel()  # type: ignore[attr-defined]
            self._refresh_current_tab()  # type: ignore[attr-defined]
            return True

        if key == leader_keys["update_sase"]:
            LeaderModeMixin._remember_leader_key(self, key, remember=remember)
            self.action_update_sase_shortcut()  # type: ignore[attr-defined]
            self._refresh_current_tab()  # type: ignore[attr-defined]
            return True

        # Unknown key - just exit mode and restore footer
        self._refresh_current_tab()  # type: ignore[attr-defined]
        return True

    def action_open_models_panel(self) -> None:
        """Open the Models panel (top-bar override pills click here)."""
        self._open_models_panel()

    def _open_models_panel(self) -> None:
        """Open the Models panel (leader ``,m`` by default)."""
        from ...modals import ModelsPanel, ModelsPanelResult
        from ...widgets import AliasOverridesIndicator, LLMOverrideIndicator

        def _refresh_indicators() -> None:
            # Refresh both top-bar override pills: the gold ``default`` pill and
            # the violet non-``default`` pill. A single override action may touch
            # either lane, so both are refreshed (each is independently skipped
            # if not mounted).
            for selector, widget_type in (
                ("#llm-override-indicator", LLMOverrideIndicator),
                ("#alias-overrides-indicator", AliasOverridesIndicator),
            ):
                try:
                    indicator = self.query_one(selector, widget_type)  # type: ignore[attr-defined]
                except Exception:
                    continue
                indicator.refresh()

        def _on_dismissed(result: ModelsPanelResult | None) -> None:
            # The panel emits its own per-action toasts; here we only refresh
            # the top-bar override pills when an override changed while the
            # panel was open.
            if result is None:
                return
            if result.changed:
                _refresh_indicators()

        self.push_screen(  # type: ignore[attr-defined]
            ModelsPanel(),
            callback=_on_dismissed,
        )

    def _update_leader_footer(self, *, current_tab: TabName = "changespecs") -> None:
        """Update the footer to show leader mode bindings.

        Args:
            current_tab: The currently active tab name.
        """
        from ...widgets import KeybindingFooter

        has_comments = False
        has_mentor_results = False
        if current_tab == "changespecs" and self.changespecs:
            cs = self.changespecs[self.current_idx]
            has_comments = bool(cs.comments)
            if cs.mentors:
                for entry in cs.mentors:
                    if entry.status_lines:
                        for sl in entry.status_lines:
                            if sl.status in ("COMMENTED", "FAILED"):
                                has_mentor_results = True
                                break
                    if has_mentor_results:
                        break

        has_notification = False
        has_unread_completed_agent = False
        has_stopped_agent = False
        has_revertable_agent = False
        marked_agent_count = 0
        if current_tab == "agents":
            from ...models.agent_status import is_revertable_agent_status

            agent = self._get_selected_agent()  # type: ignore[attr-defined]
            if agent is not None:
                has_notification = agent_is_asking(agent.status)
                has_revertable_agent = is_revertable_agent_status(agent.status)
            has_unread_completed_agent = self._has_unread_completed_agent()  # type: ignore[attr-defined]
            has_stopped_agent = self._has_stopped_agent()  # type: ignore[attr-defined]
            marked_agent_count = len(getattr(self, "_marked_agents", set()))

        try:
            footer = self.query_one("#keybinding-footer", KeybindingFooter)  # type: ignore[attr-defined]
            footer.update_leader_bindings(
                current_tab=current_tab,
                has_comments=has_comments,
                has_notification=has_notification,
                has_mentor_results=has_mentor_results,
                has_unread_completed_agent=has_unread_completed_agent,
                has_stopped_agent=has_stopped_agent,
                has_revertable_agent=has_revertable_agent,
                marked_agent_count=marked_agent_count,
            )
        except Exception:
            pass
