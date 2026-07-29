"""App actions for the Artifacts Chats pane."""

from __future__ import annotations

import asyncio
import os
import subprocess
from collections.abc import Callable, Iterable
from pathlib import Path
from typing import Any

from sase.ace.hints import build_editor_args
from sase.ace.tui.actions.clipboard import schedule_copy_delivery
from sase.ace.tui.util.pump_tasks import spawn_pump_free_task
from sase.history.chat_catalog_provenance import ChatCatalogEntry

from ..widgets._prompt_preview_target import PreviewPayload
from ..widgets.artifacts.chats_detail import chat_reference, read_full_chat
from ..widgets.artifacts.chats_pane import ArtifactsChatsPane
from ..widgets.artifacts.chats_rendering import CHAT_PROVENANCE_GLYPHS


CHATS_ARTIFACT_ACTIONS: frozenset[str] = frozenset(
    {
        "chats_next",
        "chats_prev",
        "chats_view_selected",
        "chats_filters",
        "chats_cycle_provenance",
        "chats_open_agent",
        "chats_open_external",
        "chats_copy_path",
        "chats_refresh",
    }
)


class ArtifactsChatsActionsMixin:
    """Actions mixed into :class:`ArtifactsMixin` for the Chats pane."""

    def _chats_pane(self) -> ArtifactsChatsPane | None:
        try:
            return self.query_one("#artifacts-chats-pane", ArtifactsChatsPane)  # type: ignore[attr-defined]
        except Exception:
            return None

    def action_chats_next(self) -> None:
        pane = self._chats_pane()
        if pane is not None:
            self._begin_artifacts_navigation("next")  # type: ignore[attr-defined]
            try:
                pane.move_selection(1)
            finally:
                self._finish_artifacts_navigation()  # type: ignore[attr-defined]

    def action_chats_prev(self) -> None:
        pane = self._chats_pane()
        if pane is not None:
            self._begin_artifacts_navigation("prev")  # type: ignore[attr-defined]
            try:
                pane.move_selection(-1)
            finally:
                self._finish_artifacts_navigation()  # type: ignore[attr-defined]

    def action_chats_view_selected(self) -> None:
        """Load and open the selected full transcript without blocking keys."""
        pane = self._chats_pane()
        entry = pane.selected_entry if pane is not None else None
        if entry is None:
            return
        absolute_path = entry.absolute_path

        def load_preview() -> tuple[str, str | None]:
            return read_full_chat(entry), chat_reference(entry.absolute_path)

        async def open_preview() -> None:
            content, reference = await asyncio.to_thread(load_preview)
            current_pane = self._chats_pane()
            current = current_pane.selected_entry if current_pane is not None else None
            if current is None or current.absolute_path != absolute_path:
                return
            from ..modals.preview_panel_modal import PreviewPanelModal

            self.push_screen(  # type: ignore[attr-defined]
                PreviewPanelModal(
                    PreviewPayload(
                        content=content,
                        lexer="markdown",
                        title=entry.basename,
                        kind_label="chat transcript",
                        icon=CHAT_PROVENANCE_GLYPHS[entry.provenance],
                        source_path=entry.absolute_path,
                        reference=reference,
                    )
                )
            )

        spawn_pump_free_task(
            self,
            open_preview(),
            name="sase-chat-preview",
            registry_attr="_pump_free_async_tasks",
        )

    def action_chats_filters(self) -> None:
        pane = self._chats_pane()
        if pane is not None:
            pane.show_filters()

    def action_chats_cycle_provenance(self) -> None:
        pane = self._chats_pane()
        if pane is not None:
            pane.cycle_provenance()

    def action_chats_open_agent(self) -> None:
        """Jump to the selected chat's agent, reviving it when dismissed."""
        pane = self._chats_pane()
        entry = pane.selected_entry if pane is not None else None
        if entry is None:
            return

        resolved = self._resolve_chat_agent(entry)
        if resolved is None:
            self.notify(  # type: ignore[attr-defined]
                self._missing_chat_agent_message(entry),
                severity="warning",
            )
            return

        agent, dismissed = resolved
        target_identity = agent.identity
        target_raw_suffix = agent.raw_suffix
        if dismissed:
            self._do_revive_agent(agent)  # type: ignore[attr-defined]

        self._save_current_tab_position()  # type: ignore[attr-defined]
        self.current_tab = "agents"  # type: ignore[attr-defined]

        select_agent = getattr(self, "_select_revived_agent", None)
        if callable(select_agent) and select_agent(agent):
            return
        if self._select_chat_agent(target_identity, target_raw_suffix):
            return
        self.notify(  # type: ignore[attr-defined]
            "Agent not found on Agents tab",
            severity="warning",
        )

    def _resolve_chat_agent(self, entry: ChatCatalogEntry) -> tuple[Any, bool] | None:
        """Resolve one catalog link using only already-loaded agent state."""
        artifact_dir = entry.agent_artifact_dir
        if artifact_dir is None:
            return None

        live_agents = tuple(getattr(self, "_agents", ()))
        dismissed_agents = tuple(getattr(self, "_dismissed_agent_objects", ()))
        pools = ((live_agents, False), (dismissed_agents, True))
        matchers: tuple[Callable[[Any], bool], ...] = (
            lambda agent: (
                self._agent_artifact_key(getattr(agent, "artifacts_dir", None))
                == self._agent_artifact_key(artifact_dir)
            ),
            lambda agent: (
                bool(getattr(agent, "raw_suffix", None))
                and getattr(agent, "raw_suffix", None) == Path(artifact_dir).name
            ),
            lambda agent: (
                bool(entry.agent_local_name)
                and entry.agent_local_name == getattr(agent, "agent_name", None)
            ),
        )
        for matches in matchers:
            for agents, from_dismissed in pools:
                agent = self._first_project_agent_match(entry, agents, matches)
                if agent is None:
                    continue
                return (
                    agent,
                    from_dismissed or self._chat_agent_is_dismissed(agent),
                )
        return None

    @staticmethod
    def _first_project_agent_match(
        entry: ChatCatalogEntry,
        agents: Iterable[Any],
        matches: Callable[[Any], bool],
    ) -> Any | None:
        for agent in agents:
            project_file = getattr(agent, "project_file", None)
            if entry.project_key and project_file:
                project_key = Path(project_file).parent.name
                if project_key.casefold() != entry.project_key.casefold():
                    continue
            if matches(agent):
                return agent
        return None

    @staticmethod
    def _agent_artifact_key(value: str | None) -> str | None:
        if not value:
            return None
        return os.path.normcase(os.path.abspath(os.path.expanduser(value)))

    def _chat_agent_is_dismissed(self, agent: Any) -> bool:
        identities: set[tuple[Any, ...]] = getattr(self, "_dismissed_agents", set())
        identity = getattr(agent, "identity", None)
        raw_suffix = getattr(agent, "raw_suffix", None)
        return identity in identities or (
            raw_suffix is not None
            and any(
                len(candidate) >= 3 and candidate[2] == raw_suffix
                for candidate in identities
            )
        )

    def _select_chat_agent(
        self,
        target_identity: object,
        target_raw_suffix: str | None,
    ) -> bool:
        for index, agent in enumerate(getattr(self, "_agents", ())):
            if getattr(agent, "identity", None) == target_identity:
                self.current_idx = index  # type: ignore[attr-defined]
                return True
        if target_raw_suffix:
            for index, agent in enumerate(getattr(self, "_agents", ())):
                if getattr(agent, "raw_suffix", None) == target_raw_suffix:
                    self.current_idx = index  # type: ignore[attr-defined]
                    return True
        return False

    @staticmethod
    def _missing_chat_agent_message(entry: ChatCatalogEntry) -> str:
        if entry.provenance == "remote" and entry.agent_artifact_dir is None:
            machine = entry.source_machine or "another machine"
            return (
                f"This chat was imported from {machine} and has no local agent artifact"
            )
        return "No agent is associated with this chat"

    def action_chats_open_external(self) -> None:
        """Open the selected transcript in the configured editor."""
        pane = self._chats_pane()
        entry = pane.selected_entry if pane is not None else None
        if entry is None:
            return
        editor = os.environ.get("EDITOR") or "nvim"
        editor_args = build_editor_args(editor, [entry.absolute_path])
        with self.suspend():  # type: ignore[attr-defined]
            subprocess.run(editor_args, check=False)

    def action_chats_copy_path(self) -> None:
        """Copy the selected transcript path without blocking key handling."""
        pane = self._chats_pane()
        entry = pane.selected_entry if pane is not None else None
        if entry is None:
            return

        schedule_copy_delivery(
            self,
            entry.absolute_path,
            copied_label="chat path",
            task_name="sase-chat-copy-path",
        )

    def action_chats_refresh(self) -> None:
        pane = self._chats_pane()
        if pane is not None:
            pane.request_refresh()


__all__ = ["ArtifactsChatsActionsMixin", "CHATS_ARTIFACT_ACTIONS"]
