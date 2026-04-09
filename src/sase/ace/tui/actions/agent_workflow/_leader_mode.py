"""Leader mode handling for the ace TUI app."""

from __future__ import annotations

from typing import TYPE_CHECKING

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

        if key == leader_keys["run_cmd"]:
            if self.current_tab != "changespecs":
                self._refresh_current_tab()  # type: ignore[attr-defined]
                return True
            self._start_bgcmd_from_changespec()  # type: ignore[attr-defined]
            self._refresh_current_tab()  # type: ignore[attr-defined]
            return True

        if key == leader_keys["retry_edit"]:
            if self.current_tab == "agents":
                self._retry_edit_agent()  # type: ignore[attr-defined]
                self._refresh_current_tab()  # type: ignore[attr-defined]
                return True
            # Fall through to runners (same key) on other tabs

        if key == leader_keys["runners"]:
            self.action_show_runners()  # type: ignore[attr-defined]
            self._refresh_current_tab()  # type: ignore[attr-defined]
            return True

        if key == leader_keys["kill_mentors"]:
            if self.current_tab == "changespecs":
                self.action_kill_mentors()  # type: ignore[attr-defined]
            self._refresh_current_tab()  # type: ignore[attr-defined]
            return True

        if key == leader_keys["review_mentors"]:
            if self.current_tab == "changespecs":
                self._open_mentor_review()  # type: ignore[attr-defined]
            self._refresh_current_tab()  # type: ignore[attr-defined]
            return True

        if key == leader_keys["agent_home"]:
            # Shortcut for @ → ~ (home): skip the ProjectSelectModal
            self._show_prompt_input_bar_for_home()  # type: ignore[attr-defined]
            self._refresh_current_tab()  # type: ignore[attr-defined]
            return True

        if key == leader_keys["agent_from_cl"]:
            if self.current_tab == "changespecs":
                if self.marked_indices:
                    self._start_agents_from_marked()  # type: ignore[attr-defined]
                else:
                    self._start_agent_from_changespec_quick()  # type: ignore[attr-defined]
            elif self.current_tab == "agents":
                self._start_agent_from_agent_quick()  # type: ignore[attr-defined]
            self._refresh_current_tab()  # type: ignore[attr-defined]
            return True

        if key == leader_keys["kill_and_edit"]:
            if self.current_tab == "agents":
                self._kill_and_edit_agent()  # type: ignore[attr-defined]
            self._refresh_current_tab()  # type: ignore[attr-defined]
            return True

        if key == leader_keys["kill_all"]:
            if self.current_tab == "agents":
                self._kill_and_dismiss_all_agents()  # type: ignore[attr-defined]
            self._refresh_current_tab()  # type: ignore[attr-defined]
            return True

        if key == leader_keys["task_queue"]:
            self._show_task_queue_modal()  # type: ignore[attr-defined]
            self._refresh_current_tab()  # type: ignore[attr-defined]
            return True

        if key == leader_keys["activity_info"]:
            self._show_activity_dashboard()  # type: ignore[attr-defined]
            self._refresh_current_tab()  # type: ignore[attr-defined]
            return True

        if key == leader_keys["clear_comments"]:
            if self.current_tab == "changespecs":
                self._clear_changespec_comments()  # type: ignore[attr-defined]
            self._refresh_current_tab()  # type: ignore[attr-defined]
            return True

        if key == leader_keys["jump_to_notification"]:
            if self.current_tab == "agents":
                self._jump_to_agent_notification()  # type: ignore[attr-defined]
            self._refresh_current_tab()  # type: ignore[attr-defined]
            return True

        if key == leader_keys["prompt_history"]:
            self._start_prompt_history_from_last_selection()  # type: ignore[attr-defined]
            self._refresh_current_tab()  # type: ignore[attr-defined]
            return True

        if key == leader_keys["prompt_history_cancelled"]:
            self._start_prompt_history_from_last_selection(show_cancelled=True)  # type: ignore[attr-defined]
            self._refresh_current_tab()  # type: ignore[attr-defined]
            return True

        # Unknown key - just exit mode and restore footer
        self._refresh_current_tab()  # type: ignore[attr-defined]
        return True

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
        if current_tab == "agents":
            agent = self._get_selected_agent()  # type: ignore[attr-defined]
            if agent is not None:
                has_notification = agent.status in ("PLANNING", "QUESTION")

        try:
            footer = self.query_one("#keybinding-footer", KeybindingFooter)  # type: ignore[attr-defined]
            footer.update_leader_bindings(
                current_tab=current_tab,
                has_comments=has_comments,
                has_notification=has_notification,
                has_mentor_results=has_mentor_results,
            )
        except Exception:
            pass
