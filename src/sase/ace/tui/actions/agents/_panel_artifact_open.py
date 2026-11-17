"""Opening registered artifact files from the Agents tab."""

from __future__ import annotations

import asyncio
import os
import time
import uuid
from collections.abc import Sequence
from typing import TYPE_CHECKING, Any

from ...util.pump_tasks import spawn_pump_free_task
from ...util.trace import tui_trace

if TYPE_CHECKING:
    from ...graphics import (
        ArtifactFileViewerResult,
        ArtifactViewerLaunchContext,
        TmuxPaneDecorationResult,
    )


class AgentArtifactFileOpenMixin:
    """Mixin opening artifact files in a tmux pane or a suspended viewer."""

    def _open_artifact_file(self, artifact_file: Any, *, zoom: bool = False) -> None:
        from ...graphics import is_tmux_session, view_registered_artifact_file

        if is_tmux_session():
            self._open_artifact_files_in_tmux((artifact_file,), zoom=zoom)
            return
        self._artifact_file_tmux_open_in_flight = False  # type: ignore[attr-defined]

        from ...util.external_tool import suspend_for_external_tool

        with suspend_for_external_tool(
            self,
            action="open_artifact_file",
            tool_kind="artifact_file_viewer",
            path_count=1,
            status_message="Opening artifact file…",
        ):
            result = view_registered_artifact_file(artifact_file)
        if zoom:
            self.notify(  # type: ignore[attr-defined]
                "Zoom open is only available inside tmux",
                severity="warning",
            )
        if result.warning is not None:
            self.notify(result.warning, severity="warning")  # type: ignore[attr-defined]

    def _open_artifact_files(
        self,
        artifact_files: list[Any],
        *,
        zoom: bool = False,
    ) -> None:
        if not artifact_files:
            return
        if len(artifact_files) == 1:
            self._open_artifact_file(artifact_files[0], zoom=zoom)
            return

        from ...graphics import is_tmux_session, view_registered_artifact_files

        if is_tmux_session():
            self._open_artifact_files_in_tmux(artifact_files, zoom=zoom)
            return
        self._artifact_file_tmux_open_in_flight = False  # type: ignore[attr-defined]

        from ...util.external_tool import suspend_for_external_tool

        with suspend_for_external_tool(
            self,
            action="open_artifact_files",
            tool_kind="artifact_file_viewer",
            path_count=len(artifact_files),
            status_message=f"Opening {len(artifact_files)} artifact files…",
        ):
            result = view_registered_artifact_files(artifact_files)
        if zoom:
            self.notify(  # type: ignore[attr-defined]
                "Zoom open is only available inside tmux",
                severity="warning",
            )
        if result.warning is not None:
            self.notify(result.warning, severity="warning")  # type: ignore[attr-defined]

    def _build_artifact_viewer_launch_context(self) -> ArtifactViewerLaunchContext:
        """Install the close handler and build a launch context without env mutation."""

        from ...graphics import ArtifactViewerLaunchContext

        installed = self._install_artifact_file_viewer_close_signal_handler()  # type: ignore[attr-defined]
        open_id = uuid.uuid4().hex
        open_t0 = time.time()
        return ArtifactViewerLaunchContext(
            notify_pid=os.getpid() if installed else None,
            return_pane_id=os.environ.get("TMUX_PANE") or None,
            extra_env={
                "SASE_ARTIFACT_VIEWER_OPEN_ID": open_id,
                "SASE_ARTIFACT_VIEWER_OPEN_T0": str(open_t0),
            },
            open_id=open_id,
            open_t0=open_t0,
        )

    def _launch_tmux_artifact_viewer(
        self,
        artifact_files: Sequence[Any],
        *,
        zoom: bool,
        launch: ArtifactViewerLaunchContext,
    ) -> tuple[ArtifactFileViewerResult, TmuxPaneDecorationResult | None]:
        """Split, optionally zoom, and decorate on a worker thread."""

        from ...graphics import (
            decorate_artifact_file_tmux_panes,
            view_registered_artifact_file_in_tmux_pane,
            view_registered_artifact_files_in_tmux_pane,
        )

        files = tuple(artifact_files)
        span_fields: dict[str, Any] = {"count": len(files)}
        if launch.open_id:
            span_fields["open_id"] = launch.open_id
        with tui_trace("artifact_viewer.open.split", **span_fields) as extra:
            if len(files) == 1:
                result = view_registered_artifact_file_in_tmux_pane(
                    files[0], zoom=zoom, launch=launch
                )
            else:
                result = view_registered_artifact_files_in_tmux_pane(
                    files, zoom=zoom, launch=launch
                )
            extra["ok"] = result.ok
            extra["pane_id"] = result.pane_id
        decoration = None
        if result.ok and result.pane_id is not None:
            decorate_fields: dict[str, Any] = {}
            if launch.open_id:
                decorate_fields["open_id"] = launch.open_id
            with tui_trace("artifact_viewer.open.decorate", **decorate_fields) as extra:
                decoration = decorate_artifact_file_tmux_panes(
                    result.pane_id,
                    origin_pane_id=launch.return_pane_id,
                )
                extra["ok"] = decoration.ok
        return result, decoration

    def _open_artifact_files_in_tmux(
        self,
        artifact_files: Sequence[Any],
        *,
        zoom: bool,
    ) -> None:
        """Show an opening state, then split+decorate off the UI thread."""

        self._artifact_file_tmux_open_in_flight = True  # type: ignore[attr-defined]
        self.notify("Opening artifact viewer…")  # type: ignore[attr-defined]
        files = tuple(artifact_files)
        task = None
        try:
            with tui_trace(
                "artifact_viewer.open.select",
                count=len(files),
            ) as extra:
                launch = self._build_artifact_viewer_launch_context()
                extra["open_id"] = launch.open_id
                task = spawn_pump_free_task(
                    self,
                    self._open_artifact_files_in_tmux_async(
                        files, zoom=zoom, launch=launch
                    ),
                    name="sase-agent-artifact-tmux-open",
                    registry_attr="_pump_free_async_tasks",
                )
            if task is None:
                result, decoration = self._launch_tmux_artifact_viewer(
                    files, zoom=zoom, launch=launch
                )
                self._finish_opened_artifact_file_tmux_pane(result, decoration)
        except Exception:
            self._artifact_file_tmux_open_in_flight = False  # type: ignore[attr-defined]
            raise
        else:
            if task is None:
                self._artifact_file_tmux_open_in_flight = False  # type: ignore[attr-defined]

    async def _open_artifact_files_in_tmux_async(
        self,
        artifact_files: Sequence[Any],
        *,
        zoom: bool,
        launch: ArtifactViewerLaunchContext,
    ) -> None:
        try:
            result, decoration = await asyncio.to_thread(
                self._launch_tmux_artifact_viewer,
                artifact_files,
                zoom=zoom,
                launch=launch,
            )
            self._finish_opened_artifact_file_tmux_pane(result, decoration)
        finally:
            self._artifact_file_tmux_open_in_flight = False  # type: ignore[attr-defined]

    def _finish_opened_artifact_file_tmux_pane(
        self,
        result: ArtifactFileViewerResult,
        decoration: TmuxPaneDecorationResult | None,
    ) -> None:
        """Apply pane tracking on the UI thread after the worker returns."""

        if result.ok and result.pane_id is not None:
            self._apply_opened_artifact_file_tmux_pane(  # type: ignore[attr-defined]
                result.pane_id,
                decoration,
            )
        seen: set[str] = set()
        for warning in (result.warning, getattr(decoration, "warning", None)):
            if warning and warning not in seen:
                seen.add(warning)
                self.notify(warning, severity="warning")  # type: ignore[attr-defined]

    def _open_artifact_files_materializing(
        self,
        artifact_files: list[Any],
        *,
        zoom: bool,
    ) -> None:
        """Materialize byte-free rows off the UI thread, then open + focus.

        ``spawn_pump_free_task`` closes the coroutine and returns ``None`` when
        no event loop is running (narrow unit-test/fallback callers), so that
        case runs the same materialize-then-open sequence synchronously
        instead of silently dropping the open.
        """
        missing = sum(
            1
            for artifact_file in artifact_files
            if not getattr(artifact_file, "path", None)
        )
        if missing:
            noun = "file" if missing == 1 else "files"
            self.notify(  # type: ignore[attr-defined]
                f"Fetching {missing} artifact {noun}…",
            )
        from ...graphics import is_tmux_session

        if is_tmux_session():
            self._artifact_file_tmux_open_in_flight = True  # type: ignore[attr-defined]
        task = spawn_pump_free_task(
            self,
            self._materialize_and_open_artifact_files(artifact_files, zoom=zoom),
            name="sase-agent-artifact-materialize",
            registry_attr="_pump_free_async_tasks",
        )
        if task is None:
            self._materialize_and_open_artifact_files_sync(artifact_files, zoom=zoom)

    async def _materialize_and_open_artifact_files(
        self,
        artifact_files: list[Any],
        *,
        zoom: bool,
    ) -> None:
        from ...models.artifact_file_clipboard import (
            materialize_artifact_file_entries as _materialize_artifact_file_entries,
        )

        try:
            with tui_trace(
                "artifact_viewer.open.materialize",
                count=len(artifact_files),
            ):
                materialized = await asyncio.to_thread(
                    _materialize_artifact_file_entries, tuple(artifact_files)
                )
        except (OSError, RuntimeError) as exc:
            self._finish_materialized_artifact_files_open(None, exc, zoom=zoom)
            return
        self._finish_materialized_artifact_files_open(
            list(materialized), None, zoom=zoom
        )

    def _materialize_and_open_artifact_files_sync(
        self,
        artifact_files: list[Any],
        *,
        zoom: bool,
    ) -> None:
        from ...models.artifact_file_clipboard import (
            materialize_artifact_file_entries as _materialize_artifact_file_entries,
        )

        try:
            with tui_trace(
                "artifact_viewer.open.materialize",
                count=len(artifact_files),
            ):
                materialized = _materialize_artifact_file_entries(tuple(artifact_files))
        except (OSError, RuntimeError) as exc:
            self._finish_materialized_artifact_files_open(None, exc, zoom=zoom)
            return
        self._finish_materialized_artifact_files_open(
            list(materialized), None, zoom=zoom
        )

    def _finish_materialized_artifact_files_open(
        self,
        materialized: list[Any] | None,
        error: Exception | None,
        *,
        zoom: bool,
    ) -> None:
        try:
            if error is not None:
                self._artifact_file_tmux_open_in_flight = False  # type: ignore[attr-defined]
                self.notify(  # type: ignore[attr-defined]
                    f"Could not open artifact file: {error}",
                    severity="warning",
                )
                return
            assert materialized is not None
            self._open_artifact_files(materialized, zoom=zoom)
        finally:
            self._focus_agent_list_after_artifact_modal()  # type: ignore[attr-defined]
