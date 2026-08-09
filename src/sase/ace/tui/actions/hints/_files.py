"""File viewing methods for the ace TUI app."""

from __future__ import annotations

import asyncio
import os
from pathlib import Path
from typing import TYPE_CHECKING

from ....hint_types import ViewFilesResult
from ....hints import build_editor_args
from ..clipboard import schedule_copy_delivery
from ...util.pump_tasks import spawn_pump_free_task
from ...util.trace import tui_trace
from ...widgets import AgentDetail, PatchDetail, HintInputBar
from ._types import HintMixinBase

if TYPE_CHECKING:
    from ...models.agent import Agent
    from ...widgets.prompt_panel._agent_display_state import AgentHintRender


_AGENT_HINT_RENDER_REGISTRY = "_agent_hint_render_tasks"


class FileViewingMixin(HintMixinBase):
    """Mixin providing file viewing actions."""

    def action_view_files(self) -> None:
        """View files for the current Patch or Agent, tracing the keypath.

        Wraps the whole ``v`` keypath so a capture can read the keypress →
        hint-bar-visible interval out of ``tui_trace.jsonl`` directly.
        """
        with tui_trace("agents.view_files", tab=self.current_tab):
            self._action_view_files_impl()

    def _action_view_files_impl(self) -> None:
        """View files for the current Patch or Agent."""
        if self._refocus_existing_hint_bar():
            return

        self._hint_tool_call_reports = {}
        self._hint_commit_views = {}
        if self.current_tab == "agents":
            self._view_agent_files()
            return

        patches = getattr(self, "patches", getattr(self, "changespecs", []))
        if not patches:
            return

        patch = patches[self.current_idx]

        # Re-render detail with hints
        detail_widget = self.query_one("#detail-panel", PatchDetail)  # type: ignore[attr-defined]
        query_str = self.canonical_query_string  # type: ignore[attr-defined]
        hint_mappings, _, _, _ = detail_widget.update_display_with_hints(
            patch,
            query_str,
            hints_for=None,
            hooks_collapsed=self.hooks_collapsed,  # type: ignore[attr-defined]
            stitches_collapsed=getattr(
                self,
                "stitches_collapsed",
                getattr(self, "commits_collapsed", None),
            ),
            mentors_collapsed=self.mentors_collapsed,  # type: ignore[attr-defined]
            timestamps_collapsed=self.timestamps_collapsed,  # type: ignore[attr-defined]
            deltas_collapsed=self.deltas_collapsed,  # type: ignore[attr-defined]
        )

        if not hint_mappings:  # No files available
            self.notify("No files available to view", severity="warning")  # type: ignore[attr-defined]
            self._refresh_display()  # type: ignore[attr-defined]
            return

        # Store state for later processing
        self._hint_mode_active = True
        self._hint_mode_hints_for = None  # "all" hints
        self._hint_mappings = hint_mappings
        self._hint_patch_name = patch.name
        self._hint_changespec_name = patch.name  # type: ignore[attr-defined]

        # Mount the hint input bar
        detail_container = self.query_one("#detail-container")  # type: ignore[attr-defined]
        if not detail_container.is_attached:
            return
        hint_bar = HintInputBar(mode="view", id="hint-input-bar")
        detail_container.mount(hint_bar)

    def _view_agent_files(self) -> None:
        """View files for the current agent (Agents tab), traced end to end."""
        with tui_trace("agents.view_agent_files") as extra:
            self._view_agent_files_impl(extra)

    def _view_agent_files_impl(self, extra: dict[str, object]) -> None:
        """View files for the current agent (Agents tab)."""
        if self._refocus_existing_hint_bar():
            extra["outcome"] = "refocused"
            return

        agent = self._get_selected_agent()  # type: ignore[attr-defined]
        if agent is None:
            extra["outcome"] = "no_agent"
            return

        extra["family_container"] = agent.is_family_container_row

        # Enter hint mode and paint the input before starting the annotated
        # document render. The readiness event bridges the after-refresh spawn
        # gap so a submission can never race partially published mappings.
        self._cancel_agent_hint_render_tasks()
        session = self._agent_hint_render_session
        agent_identity = tuple(agent.identity)
        ready = asyncio.Event()
        self._agent_hint_render_identity = agent_identity
        self._agent_hint_render_ready = ready
        self._hint_mode_active = True
        self._hint_mode_hints_for = None  # "all" hints
        self._hint_mappings = {}
        self._hint_tool_call_reports = {}
        self._hint_commit_views = {}
        self._hint_patch_name = agent.cl_name
        self._hint_changespec_name = agent.cl_name  # type: ignore[attr-defined]

        # Mount the hint input bar in the agent detail container
        detail_container = self.query_one("#agent-detail-container")  # type: ignore[attr-defined]
        if not detail_container.is_attached:
            self._cancel_agent_hint_render_tasks()
            self._hint_mode_active = False
            self._hint_mode_hints_for = None
            extra["outcome"] = "detached_container"
            return
        with tui_trace("agents.view_hint_bar_mount"):
            hint_bar = HintInputBar(mode="view", id="hint-input-bar")
            detail_container.mount(hint_bar)
        extra["outcome"] = "mounted_render_pending"

        agent_detail = self.query_one("#agent-detail-panel", AgentDetail)  # type: ignore[attr-defined]

        def spawn_render() -> None:
            self._spawn_agent_hint_render_task(
                agent_detail,
                agent,
                agent_identity,
                session,
                ready,
            )

        call_after_refresh = getattr(self, "call_after_refresh", None)
        if callable(call_after_refresh):
            call_after_refresh(spawn_render)
        else:
            # Narrow unit-test/fallback apps do not own a Textual refresh
            # scheduler, but still exercise the same pump-free task path.
            spawn_render()

    def _spawn_agent_hint_render_task(
        self,
        agent_detail: AgentDetail,
        agent: Agent,
        agent_identity: tuple[object, ...],
        session: int,
        ready: asyncio.Event,
    ) -> None:
        """Spawn one session-scoped annotated render outside Textual's pump."""
        if not self._agent_hint_render_session_is_current(session, agent_identity):
            ready.set()
            return

        task = spawn_pump_free_task(
            self,
            self._render_agent_hint_document(
                agent_detail,
                agent,
                agent_identity,
                session,
                ready,
            ),
            name="ace-agent-view-hints",
            registry_attr=_AGENT_HINT_RENDER_REGISTRY,
        )
        if task is None:
            ready.set()
            return
        self._agent_hint_render_task = task

    async def _render_agent_hint_document(
        self,
        agent_detail: AgentDetail,
        agent: Agent,
        agent_identity: tuple[object, ...],
        session: int,
        ready: asyncio.Event,
    ) -> AgentHintRender | None:
        """Render and publish hints only while their originating view is current."""
        try:
            # Keep this task observably deferred even in fallback apps where it
            # was not spawned from an after-refresh callback.
            await asyncio.sleep(0)
            if not self._agent_hint_render_session_is_current(session, agent_identity):
                return None

            hint_render = agent_detail.update_display_with_hints(agent)
            if not self._agent_hint_render_session_is_current(session, agent_identity):
                return None

            self._hint_mappings = hint_render.file_hints
            self._hint_tool_call_reports = hint_render.tool_call_reports
            self._hint_commit_views = hint_render.commit_views
            if (
                not hint_render.file_hints
                and not hint_render.commit_views
                and not hint_render.header_enrichment_pending
            ):
                self.notify(  # type: ignore[attr-defined]
                    "No files or commits found in agent details",
                    severity="warning",
                )
                self._remove_hint_input_bar()  # type: ignore[attr-defined]
            return hint_render
        finally:
            if self._agent_hint_render_session == session:
                self._agent_hint_render_task = None
                ready.set()

    def _agent_hint_render_session_is_current(
        self,
        session: int,
        agent_identity: tuple[object, ...],
    ) -> bool:
        """Return whether a deferred render may still publish into the UI."""
        if (
            self._agent_hint_render_session != session
            or self._agent_hint_render_identity != agent_identity
            or not self._hint_mode_active
            or self.current_tab != "agents"
        ):
            return False
        selected = self._get_selected_agent()  # type: ignore[attr-defined]
        return selected is not None and tuple(selected.identity) == agent_identity

    def _open_files_in_editor(self, result: ViewFilesResult) -> None:
        """Open files in $EDITOR (requires suspend)."""
        import subprocess

        def run_editor() -> None:
            editor = os.environ.get("EDITOR") or "nvim"
            editor_args = build_editor_args(editor, result.files)
            subprocess.run(editor_args, check=False)

        with self.suspend():  # type: ignore[attr-defined]
            run_editor()

    def _view_files_with_pager(self, files: list[str]) -> None:
        """View files using bat/cat with less (requires suspend)."""
        import shlex
        import shutil
        import subprocess

        def run_viewer() -> None:
            viewer = "bat" if shutil.which("bat") else "cat"
            quoted_files = " ".join(shlex.quote(f) for f in files)
            if viewer == "bat":
                cmd = f"bat --color=always {quoted_files} | less -R"
            else:
                cmd = f"cat {quoted_files} | less"
            subprocess.run(cmd, shell=True, check=False)

        with self.suspend():  # type: ignore[attr-defined]
            run_viewer()

    def _view_files_with_artifact_file_viewer(self, files: list[str]) -> None:
        """View selected files through the terminal artifact viewer.

        Used when the selection contains at least one supported image or video
        so media binaries render through the artifact viewer instead of being
        piped through ``bat``/``cat``. Non-media files in a mixed selection keep
        the artifact viewer's existing mode detection (Markdown, PDF, text).
        Requires suspend, matching the pager flow.
        """
        from ...graphics import (
            ArtifactFileViewSpec,
            is_supported_image_path,
            view_artifact_files,
        )

        specs = [
            ArtifactFileViewSpec(
                f,
                kind="image" if is_supported_image_path(f) else "file",
            )
            for f in files
        ]
        with self.suspend():  # type: ignore[attr-defined]
            result = view_artifact_files(specs)
        if result.warning is not None:
            self.notify(result.warning, severity="warning")  # type: ignore[attr-defined]

    def _copy_files_to_clipboard(self, files: list[str]) -> None:
        """Copy file paths to system clipboard."""
        home = str(Path.home())
        shortened_files = [
            f.replace(home, "~", 1) if f.startswith(home) else f for f in files
        ]
        content = " ".join(shortened_files)
        schedule_copy_delivery(
            self,
            content,
            copied_label=f"{len(files)} path(s)",
            task_name="sase-copy-hinted-file-paths",
        )
