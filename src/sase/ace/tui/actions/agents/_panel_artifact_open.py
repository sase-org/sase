"""Opening registered artifact files from the Agents tab."""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING, Any

from ...util.pump_tasks import spawn_pump_free_task

if TYPE_CHECKING:
    from ...graphics import ArtifactFileViewerResult


class AgentArtifactFileOpenMixin:
    """Mixin opening artifact files in a tmux pane or a suspended viewer."""

    def _open_artifact_file(self, artifact_file: Any, *, zoom: bool = False) -> None:
        from ...graphics import (
            is_tmux_session,
            view_registered_artifact_file,
            view_registered_artifact_file_in_tmux_pane,
        )

        if is_tmux_session():

            def tmux_callback() -> ArtifactFileViewerResult:
                if zoom:
                    return view_registered_artifact_file_in_tmux_pane(
                        artifact_file, zoom=True
                    )
                return view_registered_artifact_file_in_tmux_pane(artifact_file)

            result = self._with_artifact_file_viewer_notify_pid(tmux_callback)  # type: ignore[attr-defined]
            if result.ok and result.pane_id is not None:
                self._track_artifact_file_tmux_pane(result.pane_id)  # type: ignore[attr-defined]
        else:
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

        from ...graphics import (
            is_tmux_session,
            view_registered_artifact_files,
            view_registered_artifact_files_in_tmux_pane,
        )

        if is_tmux_session():

            def tmux_callback() -> ArtifactFileViewerResult:
                if zoom:
                    return view_registered_artifact_files_in_tmux_pane(
                        artifact_files, zoom=True
                    )
                return view_registered_artifact_files_in_tmux_pane(artifact_files)

            result = self._with_artifact_file_viewer_notify_pid(tmux_callback)  # type: ignore[attr-defined]
            if result.ok and result.pane_id is not None:
                self._track_artifact_file_tmux_pane(result.pane_id)  # type: ignore[attr-defined]
        else:
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
                self.notify(  # type: ignore[attr-defined]
                    f"Could not open artifact file: {error}",
                    severity="warning",
                )
                return
            assert materialized is not None
            self._open_artifact_files(materialized, zoom=zoom)
        finally:
            self._focus_agent_list_after_artifact_modal()  # type: ignore[attr-defined]
