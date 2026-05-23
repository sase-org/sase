"""Agent detail-panel actions for the ace TUI app."""

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
            # Call parent implementation for ChangeSpecs
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
        else:
            # Call parent implementation for ChangeSpecs
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
        editor = os.environ.get("EDITOR") or "nvim"
        with self.suspend():  # type: ignore[attr-defined]
            subprocess.run([editor, *chat_paths], check=False)

    def action_next_agent_file(self) -> None:
        """Cycle to the next file / next (older) chop run."""
        if self.current_tab == "agents":
            from ...widgets import AgentDetail

            agent_detail = self.query_one("#agent-detail-panel", AgentDetail)  # type: ignore[attr-defined]
            agent_detail.cycle_next_file()
        elif self.current_tab == "axe":
            self._axe_step_chop_run(direction=1)  # type: ignore[attr-defined]

    def action_prev_agent_file(self) -> None:
        """Cycle to the previous file / previous (newer) chop run."""
        if self.current_tab == "agents":
            from ...widgets import AgentDetail

            agent_detail = self.query_one("#agent-detail-panel", AgentDetail)  # type: ignore[attr-defined]
            agent_detail.cycle_prev_file()
        elif self.current_tab == "axe":
            self._axe_step_chop_run(direction=-1)  # type: ignore[attr-defined]

    def action_toggle_layout(self) -> None:
        """Toggle the layout between prompt-priority and file-priority."""
        if self.current_tab != "agents":
            return

        from ...widgets import AgentDetail

        agent_detail = self.query_one("#agent-detail-panel", AgentDetail)  # type: ignore[attr-defined]

        if agent_detail.is_info_mode() or (
            not agent_detail.is_file_visible() and not agent_detail.is_tools_visible()
        ):
            self.notify("No panel to toggle layout", severity="warning")  # type: ignore[attr-defined]
            return

        agent_detail.toggle_layout()

    def action_edit_panel(self) -> None:
        """Open the visible panel's content in $EDITOR."""
        import os
        import subprocess
        import tempfile

        if self.current_tab != "agents":
            return

        agent = self._get_selected_agent()  # type: ignore[attr-defined]
        if agent is None:
            self.notify("No agent selected", severity="warning")  # type: ignore[attr-defined]
            return

        from ...widgets import AgentDetail

        agent_detail = self.query_one("#agent-detail-panel", AgentDetail)  # type: ignore[attr-defined]
        file_path, content, suffix = agent_detail.get_editor_file_info()

        if file_path is not None:
            editor = os.environ.get("EDITOR") or "nvim"
            expanded = os.path.expanduser(file_path)
            with self.suspend():  # type: ignore[attr-defined]
                subprocess.run([editor, expanded], check=False)
        elif content is not None:
            editor = os.environ.get("EDITOR") or "nvim"
            from sase.core.paths import get_sase_tmpdir

            fd, tmp_path = tempfile.mkstemp(
                suffix=suffix, prefix="sase_ace_panel_", dir=get_sase_tmpdir()
            )
            try:
                with os.fdopen(fd, "w") as f:
                    f.write(content)
                with self.suspend():  # type: ignore[attr-defined]
                    subprocess.run([editor, tmp_path], check=False)
            finally:
                os.unlink(tmp_path)
        else:
            self.notify("No content to edit", severity="warning")  # type: ignore[attr-defined]

    def action_reset_file_trim(self) -> None:
        """Reset file trim to default page size."""
        if self.current_tab != "agents":
            return

        from ...widgets import AgentDetail

        agent_detail = self.query_one("#agent-detail-panel", AgentDetail)  # type: ignore[attr-defined]
        if not agent_detail.is_file_visible():
            return
        agent_detail.reset_file_trim()

    def action_show_all_file_lines(self) -> None:
        """Show all file lines (remove trimming)."""
        if self.current_tab != "agents":
            return

        from ...widgets import AgentDetail

        agent_detail = self.query_one("#agent-detail-panel", AgentDetail)  # type: ignore[attr-defined]
        if not agent_detail.is_file_visible():
            return
        agent_detail.show_all_file_lines()

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

    def action_toggle_thinking(self) -> None:
        """Toggle the tools panel for the selected agent."""
        self._cycle_panel_mode()

    def action_toggle_thinking_reverse(self) -> None:
        """Toggle the tools panel in reverse direction."""
        self._cycle_panel_mode(reverse=True)

    def _cycle_panel_mode(self, *, reverse: bool = False) -> None:
        """Cycle the panel mode forward or backward."""
        if self.current_tab != "agents":
            return

        agent = self._get_selected_agent()  # type: ignore[attr-defined]
        if agent is None:
            self.notify("No agent selected", severity="warning")  # type: ignore[attr-defined]
            return

        from ...widgets import AgentDetail

        agent_detail = self.query_one("#agent-detail-panel", AgentDetail)  # type: ignore[attr-defined]
        agent_detail.toggle_tools(agent, reverse=reverse)

        # Refresh footer to reflect new state
        self._refresh_agents_display()  # type: ignore[attr-defined]
