"""Open and navigation actions for the Artifacts Files pane."""

from __future__ import annotations

import asyncio
from collections.abc import Callable, Iterable
import os
from pathlib import Path
import subprocess
from typing import Any

from sase.ace.hints import build_editor_args
from sase.ace.tui.actions.clipboard import schedule_copy_delivery
from sase.ace.tui.graphics._viewer_types import ArtifactViewMode
from sase.ace.tui.models.artifact_file_clipboard import (
    ArtifactFilePathCopy,
    artifact_file_clipboard_path,
    materialize_artifact_file_entries as _materialize_artifact_file_entries,
    materialize_artifact_file_entry as _materialize_artifact_file_entry,
)
from sase.ace.tui.util.external_tool import suspend_for_external_tool
from sase.ace.tui.util.pump_tasks import spawn_pump_free_task
from sase.core.artifact_file_types import ArtifactFile

from ..widgets._prompt_preview_target import PreviewPayload
from ..widgets.file_panel import _EXTENSION_TO_LEXER
from ..widgets.artifacts.files_pane import ArtifactsFilesPane
from ..widgets.artifacts.files_rendering import FILE_VIEW_MODE_GLYPHS


FILES_ARTIFACT_ACTIONS: frozenset[str] = frozenset(
    {
        "files_next",
        "files_prev",
        "files_view_selected",
        "files_open_viewer",
        "files_open_external",
        "files_open_agent",
        "files_filters",
        "files_cycle_kind",
        "files_next_version",
        "files_prev_version",
        "files_copy_reference",
        "files_copy_path",
        "files_refresh",
    }
)


class ArtifactsFilesActionsMixin:
    """Actions mixed into :class:`ArtifactsMixin` for the Files pane."""

    def _files_pane(self) -> ArtifactsFilesPane | None:
        try:
            return self.query_one("#artifacts-files-pane", ArtifactsFilesPane)  # type: ignore[attr-defined]
        except Exception:
            return None

    def action_files_next(self) -> None:
        pane = self._files_pane()
        if pane is not None:
            self._begin_artifacts_navigation("next")  # type: ignore[attr-defined]
            try:
                pane.move_selection(1)
            finally:
                self._finish_artifacts_navigation()  # type: ignore[attr-defined]

    def action_files_prev(self) -> None:
        pane = self._files_pane()
        if pane is not None:
            self._begin_artifacts_navigation("prev")  # type: ignore[attr-defined]
            try:
                pane.move_selection(-1)
            finally:
                self._finish_artifacts_navigation()  # type: ignore[attr-defined]

    def action_files_view_selected(self) -> None:
        """Open text in the preview reader and media in the rich viewer."""

        selection = self._selected_file()
        if selection is None:
            return
        pane, entry, view_mode = selection
        if entry.path and view_mode not in {"markdown", "text"}:
            self._open_artifact_file(entry)  # type: ignore[attr-defined]
            return
        selected_id = entry.id

        async def open_preview() -> None:
            try:
                materialized = await asyncio.to_thread(
                    _materialize_artifact_file_entry,
                    entry,
                )
                assert materialized.path is not None
                stored_path = materialized.path
                if view_mode not in {"markdown", "text"}:
                    self._open_artifact_file(materialized)  # type: ignore[attr-defined]
                    return
                content = await asyncio.to_thread(
                    _read_artifact_file_text,
                    stored_path,
                )
            except (OSError, RuntimeError) as exc:
                self.notify(  # type: ignore[attr-defined]
                    f"Could not read artifact file: {exc}",
                    severity="warning",
                )
                return

            current_pane = self._files_pane()
            current = current_pane.selected_entry if current_pane is not None else None
            if current is None or current.id != selected_id:
                return

            from ..modals.preview_panel_modal import PreviewPanelModal

            lexer = (
                "markdown"
                if view_mode == "markdown"
                else _EXTENSION_TO_LEXER.get(
                    Path(stored_path).suffix.lower(),
                    "text",
                )
            )
            self.push_screen(  # type: ignore[attr-defined]
                PreviewPanelModal(
                    PreviewPayload(
                        content=content,
                        lexer=lexer,
                        title=entry.label,
                        kind_label="artifact file",
                        icon=FILE_VIEW_MODE_GLYPHS[view_mode],
                        source_path=stored_path,
                        reference=f"file:{entry.id}",
                        default_view=(
                            "rendered" if view_mode == "markdown" else "source"
                        ),
                    )
                )
            )

        spawn_pump_free_task(
            self,
            open_preview(),
            name="sase-artifact-file-preview",
            registry_attr="_pump_free_async_tasks",
        )

    def action_files_open_viewer(self) -> None:
        """Open the marked visible rows, or the selection, in one viewer."""

        toggle = getattr(self, "_toggle_tracked_artifact_file_tmux_pane", None)
        if callable(toggle) and toggle():
            return
        pane = self._files_pane()
        if pane is None:
            self._notify_no_file_selected()
            return

        marks = getattr(self, "_artifacts_marked_targets", {}).get("files", set())
        if marks:
            targets = tuple(
                target for target in pane.entry_targets() if target in marks
            )
            entries = pane.entries_for_targets(targets)
            if not entries:
                self.notify(  # type: ignore[attr-defined]
                    "No marked files entries are visible",
                    severity="warning",
                )
                return
        else:
            entry = pane.selected_entry
            if entry is None:
                self._notify_no_file_selected()
                return
            entries = (entry,)
        if all(entry.path for entry in entries):
            self._open_artifact_files(list(entries))  # type: ignore[attr-defined]
            return

        async def open_entries() -> None:
            try:
                materialized = await asyncio.to_thread(
                    _materialize_artifact_file_entries,
                    entries,
                )
            except (OSError, RuntimeError) as exc:
                self.notify(  # type: ignore[attr-defined]
                    f"Could not materialize artifact file: {exc}",
                    severity="warning",
                )
                return
            self._open_artifact_files(list(materialized))  # type: ignore[attr-defined]

        spawn_pump_free_task(
            self,
            open_entries(),
            name="sase-artifact-file-viewer",
            registry_attr="_pump_free_async_tasks",
        )

    def action_files_open_external(self) -> None:
        """Open text in the configured editor and media via xdg-open."""

        selection = self._selected_file()
        if selection is None:
            return
        _pane, entry, view_mode = selection
        if entry.path:
            stored_path = str(Path(entry.path).expanduser())
            if view_mode in {"markdown", "text"}:
                editor = os.environ.get("EDITOR") or "nvim"
                command = build_editor_args(editor, ["--", stored_path])
                self._run_external_command(
                    command,
                    action="files_open_external",
                    tool_kind="editor",
                    status_message="Opening artifact file in editor…",
                )
                return
            self._run_external_command(
                ["xdg-open", "--", stored_path],
                action="files_open_external",
                tool_kind="external_opener",
                status_message="Opening artifact file externally…",
            )
            return

        async def open_external() -> None:
            try:
                materialized = await asyncio.to_thread(
                    _materialize_artifact_file_entry,
                    entry,
                )
            except (OSError, RuntimeError) as exc:
                self.notify(  # type: ignore[attr-defined]
                    f"Could not materialize artifact file: {exc}",
                    severity="warning",
                )
                return
            assert materialized.path is not None
            stored_path = str(Path(materialized.path).expanduser())
            if view_mode in {"markdown", "text"}:
                editor = os.environ.get("EDITOR") or "nvim"
                command = build_editor_args(editor, ["--", stored_path])
                self._run_external_command(
                    command,
                    action="files_open_external",
                    tool_kind="editor",
                    status_message="Opening artifact file in editor…",
                )
                return
            self._run_external_command(
                ["xdg-open", "--", stored_path],
                action="files_open_external",
                tool_kind="external_opener",
                status_message="Opening artifact file externally…",
            )

        spawn_pump_free_task(
            self,
            open_external(),
            name="sase-artifact-file-external",
            registry_attr="_pump_free_async_tasks",
        )

    def action_files_open_agent(self) -> None:
        """Jump to the producing agent, reviving a dismissed match."""

        selection = self._selected_file()
        if selection is None:
            return
        _pane, entry, _view_mode = selection
        resolved = self._resolve_file_agent(entry)
        if resolved is None:
            self.notify(  # type: ignore[attr-defined]
                "No local agent artifact backs this file.",
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
        if self._select_file_agent(target_identity, target_raw_suffix):
            return
        self.notify(  # type: ignore[attr-defined]
            "Agent not found on Agents tab",
            severity="warning",
        )

    def action_files_filters(self) -> None:
        pane = self._files_pane()
        if pane is not None:
            pane.show_filters()

    def action_files_cycle_kind(self) -> None:
        pane = self._files_pane()
        if pane is not None:
            pane.cycle_kind()

    def action_files_next_version(self) -> None:
        pane = self._files_pane()
        if pane is not None:
            pane.select_version(1)

    def action_files_prev_version(self) -> None:
        pane = self._files_pane()
        if pane is not None:
            pane.select_version(-1)

    def action_files_copy_reference(self) -> None:
        """Copy the selected row's durable ``file:`` reference."""

        pane = self._files_pane()
        entry = pane.selected_entry if pane is not None else None
        if entry is None:
            self._notify_no_file_selected()
            return
        reference = f"file:{entry.id}"
        schedule_copy_delivery(
            self,
            reference,
            copied_label=f"reference {reference}",
            task_name="sase-copy-artifact-file-reference",
        )

    def action_files_copy_path(self) -> None:
        """Copy the selected row's anchored stored or PDF-source path."""

        pane = self._files_pane()
        entry = pane.selected_entry if pane is not None else None
        if entry is None:
            self._notify_no_file_selected()
            return

        copy_path: ArtifactFilePathCopy | None = None

        def value() -> str:
            nonlocal copy_path
            copy_path = artifact_file_clipboard_path(
                _materialize_artifact_file_entry(entry)
            )
            if copy_path is None:
                raise RuntimeError("selected artifact file has no path")
            return copy_path.text

        def copied_label() -> str:
            assert copy_path is not None
            suffix = " (no longer exists)" if copy_path.missing else ""
            return f"{copy_path.label}{suffix}: {copy_path.text}"

        schedule_copy_delivery(
            self,
            value,
            copied_label=copied_label,
            task_name="sase-copy-artifact-file-path",
        )

    def action_files_refresh(self) -> None:
        pane = self._files_pane()
        if pane is not None:
            pane.request_refresh()

    def _selected_file(
        self,
    ) -> tuple[ArtifactsFilesPane, ArtifactFile, ArtifactViewMode] | None:
        pane = self._files_pane()
        entry = pane.selected_entry if pane is not None else None
        view_mode = pane.selected_view_mode if pane is not None else None
        if pane is None or entry is None or view_mode is None:
            self._notify_no_file_selected()
            return None
        return pane, entry, view_mode

    def _notify_no_file_selected(self) -> None:
        self.notify(  # type: ignore[attr-defined]
            "No artifact file selected",
            severity="warning",
        )

    def _run_external_command(
        self,
        command: list[str],
        *,
        action: str,
        tool_kind: str,
        status_message: str,
    ) -> None:
        try:
            with suspend_for_external_tool(
                self,
                action=action,
                tool_kind=tool_kind,
                command=command[0],
                path_count=1,
                status_message=status_message,
            ):
                completed = subprocess.run(command, check=False)
        except FileNotFoundError:
            self.notify(  # type: ignore[attr-defined]
                f"{command[0]} executable not found",
                severity="warning",
            )
            return
        except OSError as exc:
            self.notify(  # type: ignore[attr-defined]
                f"Could not run {command[0]}: {exc}",
                severity="warning",
            )
            return
        if completed.returncode != 0:
            self.notify(  # type: ignore[attr-defined]
                f"{command[0]} exited with status {completed.returncode}",
                severity="warning",
            )

    def _resolve_file_agent(self, entry: ArtifactFile) -> tuple[Any, bool] | None:
        """Resolve a row link using only already-loaded live/dismissed agents."""

        if entry.agent_artifacts_dir is None and entry.agent_name is None:
            return None
        live_agents = tuple(getattr(self, "_agents", ()))
        dismissed_agents = tuple(getattr(self, "_dismissed_agent_objects", ()))
        pools = ((live_agents, False), (dismissed_agents, True))
        artifact_dir = entry.agent_artifacts_dir
        matchers: tuple[Callable[[Any], bool], ...] = (
            lambda agent: (
                artifact_dir is not None
                and self._file_agent_artifact_key(getattr(agent, "artifacts_dir", None))
                == self._file_agent_artifact_key(artifact_dir)
            ),
            lambda agent: (
                artifact_dir is not None
                and bool(getattr(agent, "raw_suffix", None))
                and getattr(agent, "raw_suffix", None) == Path(artifact_dir).name
            ),
            lambda agent: (
                bool(entry.agent_name)
                and entry.agent_name == getattr(agent, "agent_name", None)
            ),
        )
        for matches in matchers:
            for agents, from_dismissed in pools:
                agent = self._first_file_project_agent_match(entry, agents, matches)
                if agent is None:
                    continue
                return (
                    agent,
                    from_dismissed or self._file_agent_is_dismissed(agent),
                )
        return None

    @staticmethod
    def _first_file_project_agent_match(
        entry: ArtifactFile,
        agents: Iterable[Any],
        matches: Callable[[Any], bool],
    ) -> Any | None:
        for agent in agents:
            project_file = getattr(agent, "project_file", None)
            if entry.project and project_file:
                project_key = Path(project_file).parent.name
                if project_key.casefold() != entry.project.casefold():
                    continue
            if matches(agent):
                return agent
        return None

    @staticmethod
    def _file_agent_artifact_key(value: str | None) -> str | None:
        if not value:
            return None
        return os.path.normcase(os.path.abspath(os.path.expanduser(value)))

    def _file_agent_is_dismissed(self, agent: Any) -> bool:
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

    def _select_file_agent(
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


def _read_artifact_file_text(path: str) -> str:
    """Read a stored text-like artifact with tolerant UTF-8 decoding."""

    return Path(path).expanduser().read_text(encoding="utf-8", errors="replace")


__all__ = ["ArtifactsFilesActionsMixin", "FILES_ARTIFACT_ACTIONS"]
