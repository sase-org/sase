"""PromptTextArea preview command mixin."""

from __future__ import annotations

import asyncio
import os
from pathlib import Path
from typing import TYPE_CHECKING

from sase.ace.tui.widgets._prompt_preview_target import (
    PreviewError,
    PreviewToken,
    detect_preview_target_at_cursor,
    resolve_preview_target,
)

if TYPE_CHECKING:
    from textual.widgets import TextArea as _MixinBase
else:
    _MixinBase = object


class PromptPreviewMixin(_MixinBase):
    """Normal-mode preview command for xprompts, skills, workflows, and files."""

    if TYPE_CHECKING:
        _prompt_preview_request_id: int

        def _absolute_offset(self, location: tuple[int, int]) -> int: ...

    def _preview_token_under_cursor(self) -> None:
        """Resolve and open a preview for the token under the cursor."""
        offset = self._absolute_offset(self.cursor_location)
        token = detect_preview_target_at_cursor(self.text, offset)
        if token is None:
            self.notify(
                "Move the cursor onto an xprompt, skill, or file path to preview it",
                severity="warning",
            )
            return

        project, base_dir = self._preview_context()
        self._prompt_preview_request_id += 1
        request_id = self._prompt_preview_request_id
        self.run_worker(
            self._resolve_preview_async(
                token,
                project=project,
                base_dir=base_dir,
                request_id=request_id,
            ),
            name=f"prompt-preview:{request_id}",
        )

    async def _resolve_preview_async(
        self,
        token: PreviewToken,
        *,
        project: str | None,
        base_dir: str,
        request_id: int,
    ) -> None:
        try:
            payload = await asyncio.to_thread(
                resolve_preview_target,
                token,
                project=project,
                base_dir=base_dir,
            )
        except PreviewError as exc:
            if request_id == self._prompt_preview_request_id and self.is_mounted:
                self.notify(str(exc), severity="warning")
            return
        except Exception as exc:
            if request_id == self._prompt_preview_request_id and self.is_mounted:
                self.notify(f"Could not preview {token.raw}: {exc}", severity="error")
            return

        if request_id != self._prompt_preview_request_id or not self.is_mounted:
            return

        from sase.ace.tui.modals.preview_panel_modal import PreviewPanelModal

        self.app.push_screen(PreviewPanelModal(payload))

    def _preview_context(self) -> tuple[str | None, str]:
        """Return ``(project, base_dir)`` for preview resolution."""
        project: str | None = None
        base_dir = os.getcwd()
        ctx = getattr(self.app, "_prompt_context", None)
        if ctx is None:
            return project, base_dir

        is_home_mode = bool(getattr(ctx, "is_home_mode", False))
        project_name = getattr(ctx, "project_name", None)
        if isinstance(project_name, str) and project_name and not is_home_mode:
            project = project_name

        workspace_dir = getattr(ctx, "workspace_dir", "")
        if isinstance(workspace_dir, str) and workspace_dir:
            base_dir = workspace_dir
        elif is_home_mode:
            base_dir = str(Path.home())
        return project, base_dir


__all__ = ["PromptPreviewMixin"]
