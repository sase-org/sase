"""Copy actions specific to the Agents tab."""

from __future__ import annotations

import os

from ._base import ClipboardBase
from ._helpers import copy_to_system_clipboard


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

        if copy_to_system_clipboard(chat_path):
            display_path = (
                chat_path if len(chat_path) <= 50 else "..." + chat_path[-47:]
            )
            self.notify(f"Copied: {display_path}")  # type: ignore[attr-defined]
        else:
            self.notify("Failed to copy to clipboard", severity="error")  # type: ignore[attr-defined]

    def _copy_agent_name(self) -> None:
        """Copy the selected agent's name (%n on agents tab)."""
        agent = self._get_selected_agent()  # type: ignore[attr-defined]
        if agent is None:
            self.notify("No agent selected", severity="warning")  # type: ignore[attr-defined]
            return

        if agent.agent_name:
            name_value = agent.agent_name
            label = "Agent Name"
        else:
            name_value = agent.display_name
            label = "Agent Display Name"

        if copy_to_system_clipboard(name_value):
            self.notify(f"Copied: {label} ({name_value})")  # type: ignore[attr-defined]
        else:
            self.notify("Failed to copy to clipboard", severity="error")  # type: ignore[attr-defined]

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

        if copy_to_system_clipboard(content.strip()):
            lines = len(content.strip().split("\n"))
            self.notify(f"Copied: Agent Prompt ({lines} lines)")  # type: ignore[attr-defined]
        else:
            self.notify("Failed to copy to clipboard", severity="error")  # type: ignore[attr-defined]

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

        if copy_to_system_clipboard(file_path):
            display_path = (
                file_path if len(file_path) <= 50 else "..." + file_path[-47:]
            )
            self.notify(f"Copied: {display_path}")  # type: ignore[attr-defined]
        else:
            self.notify("Failed to copy to clipboard", severity="error")  # type: ignore[attr-defined]
