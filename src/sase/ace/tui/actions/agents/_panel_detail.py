"""Agent detail-panel actions for sase's TUI app."""

from __future__ import annotations

import os
import subprocess
from typing import TYPE_CHECKING

from ...models.agent_status import is_resumable_done_status
from ._panel_types import TabName

if TYPE_CHECKING:
    from ...models import Agent
    from ...models.agent import AgentType


class AgentPanelDetailMixin:
    """Mixin providing detail-panel file, chat, and tools actions."""

    current_tab: TabName
    _agents_with_children: list[Agent]
    _marked_agents: set[tuple[AgentType, str, str | None]]

    def action_show_diff(self) -> None:
        """Show diff - behavior depends on current tab."""
        if self.current_tab == "agents":
            self._refresh_agent_file()
        else:
            # Call parent implementation for Patches
            super().action_show_diff()  # type: ignore[misc]

    def _refresh_agent_file(self) -> None:
        """Refresh the file for the currently selected agent."""
        from ...widgets import AgentDetail
        from ._core import DISMISSABLE_STATUSES

        agent = self._get_selected_agent()  # type: ignore[attr-defined]
        if agent is None:
            self.notify("No agent selected", severity="warning")  # type: ignore[attr-defined]
            return
        if agent.status in DISMISSABLE_STATUSES:
            return

        agent_detail = self.query_one("#agent-detail-panel", AgentDetail)  # type: ignore[attr-defined]
        agent_detail.refresh_current_file(agent)

    def action_edit_spec(self) -> None:
        """Edit spec/chat - behavior depends on current tab."""
        if self.current_tab == "agents":
            self._open_agent_chat()
        elif self.current_tab == "services":
            self._open_selected_axe_entry_editor()  # type: ignore[attr-defined]
        else:
            # Call parent implementation for Patches
            super().action_edit_spec()  # type: ignore[misc]

    def _open_agent_chat(self) -> None:
        """Open the agent's chat file in $EDITOR."""
        if self._marked_agents:
            self._open_marked_agent_chats()
            return

        agent = self._get_selected_agent()  # type: ignore[attr-defined]
        if agent is None:
            self.notify("No agent selected", severity="warning")  # type: ignore[attr-defined]
            return

        from ._remote_lifecycle import is_remote_fleet_agent

        if is_remote_fleet_agent(agent):
            self.action_view_remote_agent_content()  # type: ignore[attr-defined]
            return

        # Only available for completed agents
        if not is_resumable_done_status(agent.status):
            self.notify("Agent not finished yet", severity="warning")  # type: ignore[attr-defined]
            return

        if not agent.response_path:
            self.notify("No chat file found", severity="warning")  # type: ignore[attr-defined]
            return

        self._open_agent_chat_paths([os.path.expanduser(agent.response_path)])

    def _open_marked_agent_chats(self) -> None:
        """Open every editable chat transcript in the marked agent set."""
        chat_paths, marked_count, skipped = self._collect_marked_agent_chat_paths()
        if marked_count == 0:
            self.notify("No marked agents remain", severity="warning")  # type: ignore[attr-defined]
            return
        if not chat_paths:
            self.notify("No chat files found in marked agents", severity="warning")  # type: ignore[attr-defined]
            return

        self._open_agent_chat_paths(chat_paths)
        if skipped:
            label = "agent" if skipped == 1 else "agents"
            self.notify(  # type: ignore[attr-defined]
                f"Skipped {skipped} marked {label} without a chat file",
                severity="warning",
            )

    def _collect_marked_agent_chat_paths(self) -> tuple[list[str], int, int]:
        """Return deduplicated chat paths, live marked count, and skip count."""
        chat_paths: list[str] = []
        seen_paths: set[str] = set()
        marked_count = 0
        skipped = 0

        for agent in self._agents_with_children:
            if agent.identity not in self._marked_agents:
                continue
            marked_count += 1
            if not is_resumable_done_status(agent.status) or not agent.response_path:
                skipped += 1
                continue
            expanded_path = os.path.expanduser(agent.response_path)
            if expanded_path in seen_paths:
                continue
            seen_paths.add(expanded_path)
            chat_paths.append(expanded_path)

        return chat_paths, marked_count, skipped

    def _open_agent_chat_paths(self, chat_paths: list[str]) -> None:
        """Open one or more chat paths in a single editor invocation."""
        from ...util.external_tool import suspend_for_external_tool

        editor = os.environ.get("EDITOR") or "nvim"
        with suspend_for_external_tool(
            self,
            action="edit_spec",
            tool_kind="editor",
            command=editor,
            path_count=len(chat_paths),
            status_message="Opening chat in editor…",
        ):
            subprocess.run([editor, *chat_paths], check=False)

    def action_next_chop_run(self) -> None:
        """Select the next (older) Services job run."""
        if self.current_tab == "services":
            self._axe_step_chop_run(direction=1)  # type: ignore[attr-defined]

    def action_prev_chop_run(self) -> None:
        """Select the previous (newer) Services job run."""
        if self.current_tab == "services":
            self._axe_step_chop_run(direction=-1)  # type: ignore[attr-defined]

    def action_next_deck_card(self) -> None:
        """Cycle to the next card in the focused deck panel (wraps)."""
        if self.current_tab != "agents":
            return
        from ...widgets import AgentDetail

        agent_detail = self.query_one("#agent-detail-panel", AgentDetail)  # type: ignore[attr-defined]
        agent_detail.cycle_focused_deck_card(1)

    def action_prev_deck_card(self) -> None:
        """Cycle to the previous card in the focused deck panel (wraps)."""
        if self.current_tab != "agents":
            return
        from ...widgets import AgentDetail

        agent_detail = self.query_one("#agent-detail-panel", AgentDetail)  # type: ignore[attr-defined]
        agent_detail.cycle_focused_deck_card(-1)

    def action_next_deck(self) -> None:
        """Cycle the focused deck panel to the next deck (wraps)."""
        if self.current_tab != "agents":
            return
        from ...widgets import AgentDetail

        agent_detail = self.query_one("#agent-detail-panel", AgentDetail)  # type: ignore[attr-defined]
        agent_detail.cycle_focused_deck(1)

    def action_prev_deck(self) -> None:
        """Cycle the focused deck panel to the previous deck (wraps)."""
        if self.current_tab != "agents":
            return
        from ...widgets import AgentDetail

        agent_detail = self.query_one("#agent-detail-panel", AgentDetail)  # type: ignore[attr-defined]
        agent_detail.cycle_focused_deck(-1)

    def action_pick_deck(self) -> None:
        """Open the deck picker for the focused deck panel."""
        if self.current_tab != "agents":
            return
        from textual.screen import ModalScreen

        from ...modals.deck_picker_modal import DeckPickerModal
        from ...widgets import AgentDetail
        from ...widgets.decks.picker import (
            DeckPick,
            build_deck_picker_rows,
            deck_picker_heading,
            deck_picker_other_hint,
        )

        if isinstance(getattr(self, "screen", None), ModalScreen):
            return
        try:
            agent_detail = self.query_one("#agent-detail-panel", AgentDetail)  # type: ignore[attr-defined]
            state = agent_detail.deck_picker_state()
        except Exception:
            return
        if state is None:
            return
        rows = build_deck_picker_rows(state)
        heading = deck_picker_heading(state)
        other_hint = (
            deck_picker_other_hint(state.other_target)
            if state.other_target is not None
            else None
        )
        try:
            from ...keymaps import split_key_alternatives
            from ...keymaps.key_validation import is_unbound_key

            registry = getattr(self, "_keymap_registry", None)
            configured = getattr(getattr(registry, "app", None), "pick_deck", "")
            raw = str(configured) if configured else ""
            close_keys = tuple(
                k for k in split_key_alternatives(raw) if k and not is_unbound_key(k)
            )
        except Exception:
            close_keys = ()

        def _on_choice(chosen: DeckPick | None) -> None:
            if chosen is None or self.current_tab != "agents":
                return
            try:
                detail = self.query_one("#agent-detail-panel", AgentDetail)  # type: ignore[attr-defined]
                if chosen.other_panel:
                    changed = detail.show_deck_in_other_panel(
                        state.panel_index, chosen.deck
                    )
                else:
                    changed = detail.apply_picked_deck(state.panel_index, chosen.deck)
            except Exception:
                return
            if not changed:
                return
            try:
                refresh = getattr(self, "_refresh_agent_footer_bindings_only", None)
                if callable(refresh):
                    refresh()
            except Exception:
                pass

        self.push_screen(  # type: ignore[attr-defined]
            DeckPickerModal(rows, heading, close_keys, other_hint), _on_choice
        )

    def action_show_deck_at(self, index: int) -> None:
        """Show one deck in the focused panel (palette direct command)."""
        if self.current_tab != "agents":
            return
        from ...widgets import AgentDetail
        from ...widgets.decks.model import DECK_CYCLE

        try:
            position = int(index)
        except Exception:
            return
        if position < 0 or position >= len(DECK_CYCLE):
            return
        try:
            agent_detail = self.query_one("#agent-detail-panel", AgentDetail)  # type: ignore[attr-defined]
            changed = agent_detail.apply_picked_deck(None, DECK_CYCLE[position])
        except Exception:
            return
        if not changed:
            return
        try:
            refresh = getattr(self, "_refresh_agent_footer_bindings_only", None)
            if callable(refresh):
                refresh()
        except Exception:
            pass

    def action_show_deck_other_at(self, index: int) -> None:
        """Show one deck in the other panel (palette direct command)."""
        if self.current_tab != "agents":
            return
        from ...widgets import AgentDetail
        from ...widgets.decks.model import DECK_CYCLE

        try:
            position = int(index)
        except Exception:
            return
        if position < 0 or position >= len(DECK_CYCLE):
            return
        try:
            agent_detail = self.query_one("#agent-detail-panel", AgentDetail)  # type: ignore[attr-defined]
            changed = agent_detail.show_deck_in_other_panel(None, DECK_CYCLE[position])
        except Exception:
            return
        if not changed:
            return
        try:
            refresh = getattr(self, "_refresh_agent_footer_bindings_only", None)
            if callable(refresh):
                refresh()
        except Exception:
            pass

    def action_zoom_panel(self) -> None:
        """Zoom the active agent or tribe detail panel."""
        if self.current_tab != "agents":
            return
        from ...widgets import AgentDetail as _DeckAgentDetail

        detail = self.query_one("#agent-detail-panel", _DeckAgentDetail)  # type: ignore[attr-defined]
        detail.toggle_deck_zoom()  # type: ignore[attr-defined]
        try:
            refresh = getattr(self, "_refresh_agent_footer_bindings_only", None)
            if callable(refresh):
                refresh()
        except Exception:
            pass

    def action_edit_panel(self) -> None:
        """Open the visible panel's content in $EDITOR."""
        import os
        import subprocess
        import tempfile

        if self.current_tab == "services":
            self._open_selected_chop_output()  # type: ignore[attr-defined]
            return
        if self.current_tab != "agents":
            return

        agent = self._get_selected_agent()  # type: ignore[attr-defined]
        if agent is None:
            self.notify("No agent selected", severity="warning")  # type: ignore[attr-defined]
            return

        from ...util.external_tool import suspend_for_external_tool
        from ...widgets import AgentDetail

        agent_detail = self.query_one("#agent-detail-panel", AgentDetail)  # type: ignore[attr-defined]
        file_path, content, suffix = agent_detail.get_editor_file_info()

        if file_path is not None:
            editor = os.environ.get("EDITOR") or "nvim"
            expanded = os.path.expanduser(file_path)
            with suspend_for_external_tool(
                self,
                action="edit_panel",
                tool_kind="editor",
                command=editor,
                path_count=1,
                status_message="Opening file in editor…",
            ):
                subprocess.run([editor, expanded], check=False)
        elif content is not None:
            editor = os.environ.get("EDITOR") or "nvim"
            from sase.core.paths import get_sase_managed_tmpdir

            fd, tmp_path = tempfile.mkstemp(
                suffix=suffix,
                prefix="sase_ace_panel_",
                dir=get_sase_managed_tmpdir("editors"),
            )
            try:
                with os.fdopen(fd, "w") as f:
                    f.write(content)
                with suspend_for_external_tool(
                    self,
                    action="edit_panel",
                    tool_kind="editor",
                    command=editor,
                    path_count=1,
                    status_message="Opening content in editor…",
                ):
                    subprocess.run([editor, tmp_path], check=False)
            finally:
                try:
                    os.unlink(tmp_path)
                except OSError:
                    pass
        else:
            self.notify("No content to edit", severity="warning")  # type: ignore[attr-defined]

    def action_toggle_attempt_view(self) -> None:
        """Toggle the attempt history view between merged and current-only."""
        if self.current_tab != "agents":
            return

        agent = self._get_selected_agent()  # type: ignore[attr-defined]
        if agent is None:
            return
        from ._loading_helpers import hydrate_agent_attempt_history

        changed = hydrate_agent_attempt_history(agent)
        if changed:
            self._invalidate_agent_panel_cache()  # type: ignore[attr-defined]
        if not agent.attempt_history:
            self.notify(  # type: ignore[attr-defined]
                "No prior attempts for this agent", severity="warning"
            )
            return
        # Attempt-pinned view renders the selected record directly; the
        # merged / current-only toggle does not apply.
        if getattr(self, "current_attempt_number", None) is not None:
            return

        from ...widgets import AgentDetail

        agent_detail = self.query_one("#agent-detail-panel", AgentDetail)  # type: ignore[attr-defined]
        agent_detail.toggle_attempt_view()
        mode = agent_detail.attempt_view_mode
        self.notify(f"Attempt view: {mode}")  # type: ignore[attr-defined]
        self._refresh_agents_display()  # type: ignore[attr-defined]

    def action_toggle_agent_header(self) -> None:
        """Toggle the agent header panel between collapsed and expanded."""
        if self.current_tab != "agents":
            return

        from ...widgets import AgentDetail

        agent_detail = self.query_one("#agent-detail-panel", AgentDetail)  # type: ignore[attr-defined]
        agent_detail.toggle_header_expanded()

    def action_toggle_agent_jump_panel(self) -> None:
        """Toggle the agent jump panel between collapsed and expanded."""
        if self.current_tab != "agents":
            return

        from ...widgets import AgentDetail

        agent_detail = self.query_one("#agent-detail-panel", AgentDetail)  # type: ignore[attr-defined]
        toggle = getattr(agent_detail, "toggle_jump_panel_expanded", None)
        if callable(toggle):
            toggle()
