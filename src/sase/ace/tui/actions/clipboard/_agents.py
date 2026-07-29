"""Copy actions specific to the Agents tab."""

from __future__ import annotations

import os
from sase.project_display_names import humanize_vcs_refs_in_text

from ._base import ClipboardBase
from ._delivery import schedule_copy_delivery


class ClipboardAgentsMixin(ClipboardBase):
    """Copy actions for entries on the Agents tab."""

    def _copy_chat_path(self) -> None:
        """Copy the chat file path of the selected agent (%c on agents tab)."""
        agent = self._get_selected_agent()  # type: ignore[attr-defined]
        if agent is None:
            self.notify("No agent selected", severity="warning")  # type: ignore[attr-defined]
            return
        if agent.response_path is None:
            self.notify("Selected agent has no chat file", severity="warning")  # type: ignore[attr-defined]
            return

        # Convert to use ~ for home directory
        chat_path = agent.response_path
        home = os.path.expanduser("~")
        if chat_path.startswith(home):
            chat_path = "~" + chat_path[len(home) :]

        display_path = chat_path if len(chat_path) <= 50 else "..." + chat_path[-47:]
        schedule_copy_delivery(
            self,
            chat_path,
            copied_label=f"chat path ({display_path})",
            task_name="sase-copy-agent-chat-path",
        )

    def _copy_agent_name(self) -> None:
        """Copy the selected agent's name (%n on agents tab)."""
        agent = self._get_selected_agent()  # type: ignore[attr-defined]
        if agent is None:
            self.notify("No agent selected", severity="warning")  # type: ignore[attr-defined]
            return

        if agent.presented_agent_name:
            name_value = agent.presented_agent_name
            label = "Agent Name"
        else:
            name_value = agent.display_name
            label = "Agent Display Name"

        schedule_copy_delivery(
            self,
            name_value,
            copied_label=f"{label.lower()} ({name_value})",
            task_name="sase-copy-agent-name",
        )

    def _copy_agent_prompt(self) -> None:
        """Copy the prompt (raw xprompt) of the selected agent (%p on agents tab)."""
        agent = self._get_selected_agent()  # type: ignore[attr-defined]
        if agent is None:
            self.notify("No agent selected", severity="warning")  # type: ignore[attr-defined]
            return
        content = agent.get_raw_xprompt_content()
        if content is None:
            self.notify("No prompt available for this agent", severity="warning")  # type: ignore[attr-defined]
            return

        display_content = humanize_vcs_refs_in_text(content).strip()
        lines = len(display_content.split("\n"))
        schedule_copy_delivery(
            self,
            display_content,
            copied_label=f"agent prompt ({lines} lines)",
            task_name="sase-copy-agent-prompt",
        )

    def _copy_file_path(self) -> None:
        """Copy the file path from the file panel (%E on agents tab)."""
        from ...widgets import AgentDetail
        from ...widgets.file_panel import AgentFilePanel

        try:
            agent_detail = self.query_one("#agent-detail-panel", AgentDetail)  # type: ignore[attr-defined]
        except Exception:
            self.notify("Agent detail panel not found", severity="warning")  # type: ignore[attr-defined]
            return

        if not agent_detail.is_file_visible():
            self.notify("File panel is not visible", severity="warning")  # type: ignore[attr-defined]
            return

        file_panel = agent_detail.query_one("#agent-file-panel", AgentFilePanel)
        file_path = file_panel.get_current_file_path()
        if file_path is None:
            self.notify("No file path (showing diff output)", severity="warning")  # type: ignore[attr-defined]
            return

        # Convert to use ~ for home directory
        home = os.path.expanduser("~")
        if file_path.startswith(home):
            file_path = "~" + file_path[len(home) :]

        display_path = file_path if len(file_path) <= 50 else "..." + file_path[-47:]
        schedule_copy_delivery(
            self,
            file_path,
            copied_label=f"file path ({display_path})",
            task_name="sase-copy-agent-file-path",
        )
