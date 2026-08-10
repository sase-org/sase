"""Agent detail-panel actions for the ace TUI app."""

from __future__ import annotations

import os
import subprocess
from collections.abc import Callable
from typing import TYPE_CHECKING, Any, cast

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
        elif self.current_tab == "axe":
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

    def action_zoom_panel(self) -> None:
        """Zoom the active agent or tribe detail panel."""
        if self.current_tab != "agents":
            return

        from ...modals import ZoomPanelModal, ZoomPanelTarget
        from ...widgets import AgentDetail

        agent_detail = self.query_one("#agent-detail-panel", AgentDetail)  # type: ignore[attr-defined]
        tribe_resolver = getattr(self, "_focused_tribe_summary", None)
        tribe_summary_provider = (
            cast(Callable[..., Any], tribe_resolver)
            if callable(tribe_resolver)
            else None
        )
        tribe_snapshot = (
            tribe_summary_provider(with_entry_target=False)
            if tribe_summary_provider is not None
            else None
        )
        if tribe_snapshot is not None:
            assert tribe_summary_provider is not None
            focused_tribe_summary = tribe_summary_provider
            panel_identity = tribe_snapshot.container_identity

            def tribe_provider() -> Any:
                snapshot = focused_tribe_summary(with_entry_target=False)
                if snapshot is None or snapshot.container_identity != panel_identity:
                    return None
                return snapshot

            self.push_screen(  # type: ignore[attr-defined]
                ZoomPanelModal(
                    tribe_provider=tribe_provider,
                    initial_tribe=tribe_snapshot,
                    initial_target=ZoomPanelTarget.METADATA,
                    seed=self._zoom_seed_for_tribe(agent_detail),
                    refresh_interval=getattr(self, "refresh_interval", 10),
                )
            )
            return

        agent = self._get_selected_agent()  # type: ignore[attr-defined]
        if agent is None:
            self.notify("No agent selected", severity="warning")  # type: ignore[attr-defined]
            return

        target = self._zoom_target_for_detail(agent_detail)
        seed = self._zoom_seed_from_detail(agent_detail)
        agent_identity = agent.identity

        def agent_provider() -> Agent | None:
            for candidate in list(getattr(self, "_agents", [])) + list(
                getattr(self, "_agents_with_children", [])
            ):
                if candidate.identity == agent_identity:
                    return candidate
            return None

        self.push_screen(  # type: ignore[attr-defined]
            ZoomPanelModal(
                agent_provider=agent_provider,
                initial_agent=agent,
                initial_target=target,
                seed=seed,
                refresh_interval=getattr(self, "refresh_interval", 10),
            )
        )

    def _zoom_seed_for_tribe(self, agent_detail: Any) -> Any:
        """Capture the focused tribe document for the zoom modal's first paint."""
        from ...modals import ZoomPanelSeed
        from ...widgets.prompt_panel import AgentPromptPanel

        prompt_panel = agent_detail.query_one("#agent-prompt-panel", AgentPromptPanel)
        return ZoomPanelSeed(
            metadata_renderable=getattr(prompt_panel, "content", None),
            metadata_subtitle=self._zoom_border_subtitle(
                agent_detail, "#agent-prompt-scroll"
            ),
            has_file_content=False,
            has_tools_content=False,
        )

    def _zoom_target_for_detail(self, agent_detail: Any) -> Any:
        """Choose the initial zoom target from the base Agents detail state."""
        from ...modals import ZoomPanelTarget

        if getattr(self, "current_attempt_number", None) is not None:
            return ZoomPanelTarget.METADATA
        if agent_detail.is_info_mode():
            return ZoomPanelTarget.METADATA
        if agent_detail.is_layout_swapped():
            return ZoomPanelTarget.METADATA
        if agent_detail.is_tools_visible():
            return ZoomPanelTarget.TOOLS
        if agent_detail.is_file_visible():
            return ZoomPanelTarget.FILE
        return ZoomPanelTarget.METADATA

    def _zoom_seed_from_detail(self, agent_detail: Any) -> Any:
        """Capture lightweight render state for the zoom modal's first paint."""
        from ...modals import ZoomPanelSeed
        from ...widgets.file_panel import AgentFilePanel
        from ...widgets.prompt_panel import AgentPromptPanel
        from ...widgets.tools_panel import AgentToolsPanel, ToolDetailLevel

        prompt_panel = agent_detail.query_one("#agent-prompt-panel", AgentPromptPanel)
        file_panel = agent_detail.query_one("#agent-file-panel", AgentFilePanel)
        tools_panel = agent_detail.query_one("#agent-tools-panel", AgentToolsPanel)
        file_list = tuple(getattr(file_panel, "_file_list", ()))
        raw_tools_detail_level = getattr(agent_detail, "tools_detail_level", None)
        if raw_tools_detail_level is None:
            raw_tools_detail_level = getattr(
                tools_panel, "detail_level", ToolDetailLevel.COMPACT
            )
        tools_detail_level = ToolDetailLevel(
            int(cast(ToolDetailLevel | int, raw_tools_detail_level))
        )
        return ZoomPanelSeed(
            metadata_renderable=getattr(prompt_panel, "content", None),
            file_renderable=getattr(file_panel, "content", None),
            tools_renderable=getattr(tools_panel, "content", None),
            metadata_subtitle=self._zoom_border_subtitle(
                agent_detail, "#agent-prompt-scroll"
            ),
            file_subtitle=self._zoom_border_subtitle(
                agent_detail, "#agent-file-scroll"
            ),
            tools_subtitle=self._zoom_border_subtitle(
                agent_detail, "#agent-tools-scroll"
            ),
            file_list=file_list,
            file_index=getattr(file_panel, "current_file_index", 0),
            has_file_content=bool(
                agent_detail.is_file_visible()
                or getattr(agent_detail, "_has_file_content", False)
            ),
            has_tools_content=bool(
                agent_detail.is_tools_visible()
                or getattr(agent_detail, "_has_tools_content", False)
            ),
            tools_detail_level=tools_detail_level,
            attempt_view_mode=getattr(agent_detail, "attempt_view_mode", "merged"),
            attempt_number=getattr(self, "current_attempt_number", None),
        )

    def _zoom_border_subtitle(self, agent_detail: Any, selector: str) -> Any:
        """Return a base detail scroll subtitle, if that scroll exists."""
        try:
            scroll = agent_detail.query_one(selector)
        except Exception:
            return None
        return getattr(scroll, "border_subtitle", None)

    def action_edit_panel(self) -> None:
        """Open the visible panel's content in $EDITOR."""
        import os
        import subprocess
        import tempfile

        if self.current_tab == "axe":
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
