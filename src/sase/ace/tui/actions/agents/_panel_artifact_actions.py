"""Agents-tab artifact-file actions and selection-modal plumbing."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from ._panel_types import TabName

if TYPE_CHECKING:
    from ...models import Agent
    from ...models.agent import AgentType


class AgentArtifactFileActionMixin:
    """Mixin providing the artifact-file keybinding actions and their helpers."""

    current_tab: TabName
    _agents_with_children: list[Agent]
    _marked_agents: set[tuple[AgentType, str, str | None]]

    def _focus_agent_list_after_artifact_modal(self) -> None:
        if self.current_tab != "agents":
            return
        try:
            from ...widgets import AgentList

            self.query_one("#agent-list-panel", AgentList).focus()  # type: ignore[attr-defined]
        except Exception:
            return

    def _artifact_file_prefix_label(self, agent: Agent) -> str:
        """Return a short, human-readable prefix to identify *agent* in the picker."""
        name = agent.display_name or ""
        agent_name = getattr(agent, "agent_name", None) or ""
        if agent_name and agent_name != name:
            return f"{name} @{agent_name}" if name else f"@{agent_name}"
        return name

    def _collect_marked_artifact_files(
        self,
    ) -> tuple[list[Any], list[str | None], int]:
        """Return artifact files, labels, and the marked-agent count."""
        marked: list[Agent] = [
            a for a in self._agents_with_children if a.identity in self._marked_agents
        ]
        artifact_files: list[Any] = []
        labels: list[str | None] = []
        for agent in marked:
            agent_label = self._artifact_file_prefix_label(agent)
            for artifact_file in self._list_selected_artifact_files(agent):  # type: ignore[attr-defined]
                artifact_files.append(artifact_file)
                labels.append(agent_label)
        return artifact_files, labels, len(marked)

    def action_open_artifact_files(self) -> None:
        """Open or choose artifact files associated with the selected agent."""
        if self.current_tab != "agents":
            return
        if self._toggle_tracked_artifact_file_tmux_pane():  # type: ignore[attr-defined]
            return

        from ...modals import ArtifactFileSelectionModal

        def _open_selected(selection: Any) -> None:
            selected_artifact_files, zoom = self._normalize_artifact_file_selection(
                selection
            )
            if not selected_artifact_files:
                self._focus_agent_list_after_artifact_modal()
                return
            if all(
                getattr(artifact_file, "path", None)
                for artifact_file in selected_artifact_files
            ):
                try:
                    self._open_artifact_files(selected_artifact_files, zoom=zoom)  # type: ignore[attr-defined]
                finally:
                    self._focus_agent_list_after_artifact_modal()
                return
            self._open_artifact_files_materializing(  # type: ignore[attr-defined]
                selected_artifact_files, zoom=zoom
            )

        if self._marked_agents:
            artifact_files, labels, marked_count = self._collect_marked_artifact_files()
            if marked_count == 0:
                self.notify(  # type: ignore[attr-defined]
                    "No marked agents remain",
                    severity="warning",
                )
                return
            if not artifact_files:
                self.notify(  # type: ignore[attr-defined]
                    "No artifact files found in marked agents",
                    severity="warning",
                )
                return
            self.push_screen(  # type: ignore[attr-defined]
                ArtifactFileSelectionModal(
                    artifact_files,
                    agent_labels=labels,
                    agent_count=marked_count,
                ),
                _open_selected,
            )
            return

        agent = self._get_selected_agent()  # type: ignore[attr-defined]
        if agent is None:
            self.notify("No agent selected", severity="warning")  # type: ignore[attr-defined]
            return

        artifact_files = self._list_selected_artifact_files(agent)  # type: ignore[attr-defined]
        if not artifact_files:
            message = (
                "No completed artifact files for this agent"
                if agent.status not in ("DONE", "FAILED")
                else "No artifact files found"
            )
            self.notify(message, severity="warning")  # type: ignore[attr-defined]
            return

        self.push_screen(ArtifactFileSelectionModal(artifact_files), _open_selected)  # type: ignore[attr-defined]

    def _normalize_artifact_file_selection(
        self,
        selection: Any,
    ) -> tuple[list[Any], bool]:
        from ...modals import ArtifactFileSelectionResult

        if selection is None:
            return [], False
        if isinstance(selection, ArtifactFileSelectionResult):
            return selection.artifact_files, selection.zoom
        if isinstance(selection, list):
            return selection, False
        return [selection], False

    def action_view_image(self) -> None:
        """Compatibility wrapper for older keymaps."""
        self.action_open_artifact_files()
