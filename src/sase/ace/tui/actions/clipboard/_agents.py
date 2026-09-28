"""Copy actions specific to the Agents tab."""

from __future__ import annotations

import os

from sase.project_display_names import humanize_vcs_refs_in_text

from ._artifact_reference_resolution import reference_for_agent_row
from ._base import ClipboardBase
from ._delivery import schedule_copy_delivery
from ._helpers import cap_copy_content


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

        capped = cap_copy_content(humanize_vcs_refs_in_text(content).strip())
        lines = len(capped.value.split("\n"))
        schedule_copy_delivery(
            self,
            capped.value,
            copied_label=(
                f"agent prompt ({lines} lines) — truncated"
                if capped.truncated
                else f"agent prompt ({lines} lines)"
            ),
            task_name="sase-copy-agent-prompt",
        )

    def _copy_agent_reference(self) -> None:
        """Copy the durable reference for a concrete Agents-tab agent row."""
        agent = self._get_selected_agent()  # type: ignore[attr-defined]
        if agent is None:
            self.notify("No agent selected", severity="warning")  # type: ignore[attr-defined]
            return
        if agent.is_clan_container:
            self.notify(  # type: ignore[attr-defined]
                "The selected clan row has no agent reference",
                severity="warning",
            )
            return
        if agent.is_agent_session_container_row:
            self.notify(  # type: ignore[attr-defined]
                "The selected session container has no agent reference",
                severity="warning",
            )
            return
        if not agent.is_agent_entry:
            row_kind = "workflow step" if agent.is_workflow_step_child else "workflow"
            self.notify(  # type: ignore[attr-defined]
                f"The selected {row_kind} row has no agent reference",
                severity="warning",
            )
            return
        reference = reference_for_agent_row(agent)
        if reference is None:
            self.notify(  # type: ignore[attr-defined]
                "The selected agent has no durable agent name",
                severity="warning",
            )
            return
        schedule_copy_delivery(
            self,
            f"@{reference}",
            copied_label=f"agent reference ({reference})",
            task_name="sase-copy-agent-reference",
        )

    def _copy_tool_run_id(self) -> None:
        """Copy the selected Runs block's run id, else the header chip's."""
        agent = self._get_selected_agent()  # type: ignore[attr-defined]
        if agent is None:
            self.notify("No agent selected", severity="warning")  # type: ignore[attr-defined]
            return
        run_id = self._selected_tool_runs_block_run_id()
        if not run_id:
            from ...tool_runs.header_chip import header_run_id_for_agent

            run_id = header_run_id_for_agent(self, agent)
        if not run_id:
            self.notify("No tool runs for this agent", severity="warning")  # type: ignore[attr-defined]
            return
        schedule_copy_delivery(
            self,
            run_id,
            copied_label=f"tool run id ({run_id[:8]})",
            task_name="sase-copy-agent-tool-run-id",
        )

    def _selected_tool_runs_block_run_id(self) -> str | None:
        """Return the selected ``⚒ Runs`` block's run id, if any.

        Only applies while the focused panel shows the Tools deck with
        the ``runs`` card active; otherwise None so the caller falls
        back to the header chip's run. Never raises.
        """
        try:
            from ...widgets import AgentDetail
            from ...widgets.decks.model import DeckId

            agent_detail = self.query_one("#agent-detail-panel", AgentDetail)  # type: ignore[attr-defined]
            panel = agent_detail.deck_area.focused_panel()
            if panel.deck != DeckId.TOOLS:
                return None
            if panel.active_tools_card() != "runs":
                return None
            block_id = panel.tool_runs_view.active_block_id("runs")
        except Exception:
            return None
        if not block_id:
            return None
        return str(block_id)

    def _copy_file_path(self) -> None:
        """Copy the file path from the file panel (%E on agents tab)."""
        from ...widgets import AgentDetail

        try:
            agent_detail = self.query_one("#agent-detail-panel", AgentDetail)  # type: ignore[attr-defined]
        except Exception:
            self.notify("Agent detail panel not found", severity="warning")  # type: ignore[attr-defined]
            return

        file_panel = agent_detail.focused_file_view()  # type: ignore[attr-defined]
        if file_panel is None:
            self.notify("File panel is not visible", severity="warning")  # type: ignore[attr-defined]
            return
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
