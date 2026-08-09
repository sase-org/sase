"""Shared source-file handoffs for TUI modals."""

from __future__ import annotations

import os
import subprocess

from sase.ace.tui.actions.artifact_viewer_handoff import open_artifact_path
from sase.ace.tui.actions.clipboard import schedule_copy_delivery
from sase.ace.tui.util.external_tool import suspend_for_external_tool
from sase.ace.tui.widgets._prompt_jump_target import build_jump_editor_argv


class SourceFileActionsMixin:
    """Mixin for modal actions backed by one optional source file."""

    def _source_action_path(self) -> str | None:
        return None

    def _source_action_position(self) -> tuple[int | None, int | None]:
        return None, None

    def action_copy_path(self) -> None:
        path = self._source_action_path()
        if path is None:
            self.notify(  # type: ignore[attr-defined]
                "This preview does not have a path to copy",
                severity="warning",
            )
            return
        schedule_copy_delivery(
            self,
            path,
            copied_label="path",
            task_name="sase-preview-copy-path",
        )

    def action_open_in_editor(self) -> None:
        path = self._source_action_path()
        if path is None:
            self.notify(  # type: ignore[attr-defined]
                "This preview does not have a file to edit",
                severity="warning",
            )
            return
        line, col = self._source_action_position()
        editor = os.environ.get("EDITOR") or "nvim"
        editor_args = build_jump_editor_argv(editor, path, line, col)
        with suspend_for_external_tool(
            self.app,  # type: ignore[attr-defined]
            action="preview_open_editor",
            tool_kind="editor",
            command=editor_args[0],
            path_count=1,
        ):
            subprocess.run(editor_args, check=False)

    def action_open_in_viewer(self) -> None:
        path = self._source_action_path()
        if path is None:
            self.notify(  # type: ignore[attr-defined]
                "This preview does not have a file to view",
                severity="warning",
            )
            return
        open_artifact_path(self.app, path)  # type: ignore[attr-defined]


__all__ = ["SourceFileActionsMixin"]
