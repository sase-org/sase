"""Copy actions specific to the Agents tab."""

from __future__ import annotations

import json
import os
from typing import Any

from sase.project_display_names import humanize_vcs_refs_in_text

from ._artifact_reference_resolution import reference_for_agent_row
from ._base import ClipboardBase
from ._delivery import schedule_copy_delivery
from ._helpers import cap_copy_content, format_markdown_link


def _agent_copy_target(owner: Any) -> Any | None:
    """Return the Archive-aware Agents-tab agent for copy callers."""
    from ..agents._archive_actions import resolve_agents_read_agent

    try:
        return resolve_agents_read_agent(owner)
    except Exception:
        return None


def _agent_reference_or_notify(owner: Any) -> str | None:
    """Return the durable ``agent:`` reference or warn why there is none."""
    agent = _agent_copy_target(owner)
    if agent is None:
        owner.notify("No agent selected", severity="warning")  # type: ignore[attr-defined]
        return None
    if getattr(agent, "is_clan_container", False):
        owner.notify(  # type: ignore[attr-defined]
            "The selected clan row has no agent reference",
            severity="warning",
        )
        return None
    if getattr(agent, "is_agent_session_container_row", False):
        owner.notify(  # type: ignore[attr-defined]
            "The selected session container has no agent reference",
            severity="warning",
        )
        return None
    if not getattr(agent, "is_agent_entry", False):
        row_kind = (
            "workflow step"
            if getattr(agent, "is_workflow_step_child", False)
            else "workflow"
        )
        owner.notify(  # type: ignore[attr-defined]
            f"The selected {row_kind} row has no agent reference",
            severity="warning",
        )
        return None
    reference = reference_for_agent_row(agent)
    if reference is None:
        owner.notify(  # type: ignore[attr-defined]
            "The selected agent has no durable agent name",
            severity="warning",
        )
        return None
    return reference


class ClipboardAgentsMixin(ClipboardBase):
    """Copy actions for entries on the Agents tab."""

    def _copy_chat_path(self) -> None:
        """Copy the chat file path of the selected agent (%c on agents tab)."""
        from ..agents._archive_actions import resolve_agents_read_agent

        agent = resolve_agents_read_agent(self)
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
        from ..agents._archive_actions import resolve_agents_read_agent

        agent = resolve_agents_read_agent(self)
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
        """Copy the prompt (raw macro) of the selected agent (%p on agents tab)."""
        from ..agents._archive_actions import resolve_agents_read_agent

        agent = resolve_agents_read_agent(self)
        if agent is None:
            self.notify("No agent selected", severity="warning")  # type: ignore[attr-defined]
            return
        content = agent.get_raw_prompt_content()
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

    def action_agents_copy_reference(self) -> None:
        """Copy the selected agent's durable ``@agent:`` reference.

        Tab-disjoint duplicate of ``artifacts_copy_reference`` on ``y``:
        Inbox and Archive both copy the concrete row's paste-ready
        ``@agent:`` reference.
        """
        if getattr(self, "current_tab", None) != "agents":
            return
        self._copy_agent_reference()

    def _copy_agent_reference(self) -> None:
        """Copy the durable reference for a concrete Agents-tab agent row."""
        from ..agents._archive_actions import resolve_agents_read_agent

        agent = resolve_agents_read_agent(self)
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

    def _copy_agent_handoff(self) -> None:
        """Prefill a new agent prompt with the selected agent's reference (%!)."""
        reference = _agent_reference_or_notify(self)
        if reference is None:
            return
        show_prompt = getattr(self, "_show_prompt_input_bar_for_home", None)
        if not callable(show_prompt):
            schedule_copy_delivery(
                self,
                f"@{reference}",
                copied_label=f"agent reference ({reference})",
                task_name="sase-copy-agent-reference",
            )
            return
        agent = _agent_copy_target(self)
        history_key = "handoff"
        try:
            history_key = (
                getattr(agent, "cl_name", None)
                or getattr(agent, "presented_agent_name", None)
                or "handoff"
            )
        except Exception:
            pass
        try:
            show_prompt(
                initial_text=f"@{reference} ",
                display_name=f"handoff({reference})",
                history_sort_key=str(history_key),
            )
        except Exception:
            self.notify("Handoff prompt failed to open", severity="error")  # type: ignore[attr-defined]

    def _copy_agent_link(self) -> None:
        """Copy a followable Markdown link for the selected agent (%l)."""
        reference = _agent_reference_or_notify(self)
        if reference is None:
            return
        link = format_markdown_link(f"@{reference}", reference)
        schedule_copy_delivery(
            self,
            link,
            copied_label=f"agent link ({reference})",
            task_name="sase-copy-agent-link",
        )

    def _copy_agent_json(self) -> None:
        """Copy the selected agent's metadata JSON (%j)."""
        try:
            from ..agents._archive_actions import archive_ui_active

            archived = bool(archive_ui_active(self))
        except Exception:
            archived = False
        if archived:
            # Capture the run at keypress: the worker never re-reads the
            # selection, which may have moved by the time it runs.
            from ...models.agent_archive_view import ARCHIVE_ROW_AGENT
            from ..agents._archive_view import get_agents_tab_selection

            selection = get_agents_tab_selection(self)
            light_row = selection.light_row
            if selection.row_kind != ARCHIVE_ROW_AGENT or light_row is None:
                self.notify("No archived run selected", severity="warning")  # type: ignore[attr-defined]
                return

            def _read_bundle() -> str:
                from ..agents._archive_reader import read_archive_bundle_json

                return read_archive_bundle_json(self, light_row)

            schedule_copy_delivery(
                self,
                _read_bundle,
                copied_label="archive bundle JSON",
                task_name="sase-copy-agent-json",
            )
            return
        agent = _agent_copy_target(self)
        if agent is None:
            self.notify("No agent selected", severity="warning")  # type: ignore[attr-defined]
            return
        record: dict[str, Any] = {}
        for field in (
            "agent_name",
            "presented_agent_name",
            "display_name",
            "cl_name",
            "status",
            "project_display_name",
            "project_query_name",
            "model",
            "response_path",
            "artifacts_dir",
        ):
            try:
                value = getattr(agent, field, None)
            except Exception:
                value = None
            if value is not None:
                record[field] = value
        try:
            payload = json.dumps(record, indent=2, sort_keys=True, default=str)
        except Exception:
            self.notify("Agent metadata is not serializable", severity="warning")  # type: ignore[attr-defined]
            return
        schedule_copy_delivery(
            self,
            payload,
            copied_label="agent metadata JSON",
            task_name="sase-copy-agent-json",
        )

    def _copy_agent_artifacts_dir(self) -> None:
        """Copy the selected agent's artifacts directory path (%d)."""
        agent = _agent_copy_target(self)
        if agent is None:
            self.notify("No agent selected", severity="warning")  # type: ignore[attr-defined]
            return
        try:
            artifacts_dir = getattr(agent, "artifacts_dir", None)
        except Exception:
            artifacts_dir = None
        if not artifacts_dir:
            self.notify("Selected agent has no artifacts directory", severity="warning")  # type: ignore[attr-defined]
            return
        try:
            from sase.core.agent_artifact_paths import resolve_agent_artifact_path

            resolved = str(resolve_agent_artifact_path(artifacts_dir))
        except Exception:
            self.notify("Artifacts directory could not be resolved", severity="warning")  # type: ignore[attr-defined]
            return
        home = os.path.expanduser("~")
        if resolved.startswith(home):
            resolved = "~" + resolved[len(home) :]
        display_path = resolved if len(resolved) <= 50 else "..." + resolved[-47:]
        schedule_copy_delivery(
            self,
            resolved,
            copied_label=f"artifacts dir ({display_path})",
            task_name="sase-copy-agent-artifacts-dir",
        )

    def _copy_tool_run_id(self) -> None:
        """Copy the selected Runs block's run id, else the header chip's."""
        from ..agents._archive_actions import resolve_agents_read_agent

        agent = resolve_agents_read_agent(self)
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
