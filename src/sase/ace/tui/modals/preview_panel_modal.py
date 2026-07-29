"""Scrollable syntax-highlighted preview modal."""

from __future__ import annotations

import asyncio
import os
import subprocess

from rich.console import RenderableType
from rich.text import Text
from textual.app import ComposeResult
from textual.containers import Container, VerticalScroll
from textual.screen import ModalScreen
from textual.widgets import Static

from sase.ace.hints import build_editor_args
from sase.ace.tui.actions.artifact_viewer_handoff import open_artifact_path
from sase.ace.tui.actions.clipboard import copy_to_system_clipboard
from sase.ace.tui.util.external_tool import suspend_for_external_tool
from sase.ace.tui.util.lazy_syntax import LazySyntaxRenderCache, lazy_renderable
from sase.ace.tui.util.pump_tasks import (
    cancel_pump_free_tasks,
    spawn_pump_free_task,
)
from sase.ace.tui.widgets._prompt_preview_target import PreviewPayload

from .base import CopyModeForwardingMixin


_COLOR_MUTED = "dim #87D7FF"


class PreviewPanelModal(CopyModeForwardingMixin, ModalScreen[None]):
    """Presentational modal for resolved xprompt/file previews."""

    BINDINGS = [
        ("escape", "close", "Close"),
        ("q", "close", "Close"),
        ("y", "copy_contents", "Copy contents"),
        ("Y", "copy_path", "Copy path"),
        ("shift+y", "copy_path", "Copy path"),
        ("o", "open_in_editor", "Open in editor"),
        ("Z", "open_in_viewer", "Open in viewer"),
        ("shift+z", "open_in_viewer", "Open in viewer"),
        ("ctrl+d", "scroll_down", "Scroll down"),
        ("ctrl+u", "scroll_up", "Scroll up"),
        ("j", "scroll_line_down", "Line down"),
        ("k", "scroll_line_up", "Line up"),
        ("g", "scroll_top", "Top"),
        ("G", "scroll_bottom", "Bottom"),
        ("shift+g", "scroll_bottom", "Bottom"),
    ]

    def __init__(self, payload: PreviewPayload) -> None:
        super().__init__()
        self._payload = payload
        self._syntax_render_cache = LazySyntaxRenderCache()

    def compose(self) -> ComposeResult:
        with Container(id="preview-modal-container"):
            yield Static(self._build_title(), id="preview-title")
            with VerticalScroll(id="preview-scroll"):
                yield Static(self._build_content(), id="preview-content")
            yield Static(self._build_footer(), id="preview-footer")

    def on_unmount(self) -> None:
        cancel_pump_free_tasks(self)

    def _build_title(self) -> Text:
        text = Text()
        text.append(self._payload.icon, style="bold #FFD700")
        text.append(" ")
        text.append(self._payload.kind_label.upper(), style="bold #87D7FF")
        text.append("  ")
        text.append(self._payload.title, style="bold white")
        if self._payload.reference:
            text.append("\n")
            text.append(self._payload.reference, style=_COLOR_MUTED)
            if self._payload.source_path:
                text.append("  →  ", style="dim")
                text.append(self._payload.source_path, style=_COLOR_MUTED)
        elif self._payload.source_path:
            text.append("\n")
            text.append(self._payload.source_path, style=_COLOR_MUTED)
        return text

    def _build_footer(self) -> str:
        parts = [
            "j/k scroll",
            "ctrl+d/u page",
            "g/G top/bottom",
            "y contents",
        ]
        if self._payload.source_path:
            parts.extend(("Y path", "% copy", "o editor", "Z viewer"))
        else:
            parts.append("% copy")
        parts.append("esc close")
        return " | ".join(parts)

    def _build_content(self) -> RenderableType:
        return lazy_renderable(
            self._payload.content,
            self._payload.lexer,
            line_numbers=True,
            theme="monokai",
            render_cache=self._syntax_render_cache,
        )

    def action_close(self) -> None:
        self.dismiss(None)

    def action_copy_contents(self) -> None:
        self._schedule_copy(
            self._payload.content,
            copied_message=f"Copied {self._payload.kind_label} contents",
            task_name="sase-preview-copy-contents",
        )

    def action_copy_path(self) -> None:
        path = self._payload.source_path
        if path is None:
            self.notify(
                "This preview does not have a path to copy",
                severity="warning",
            )
            return
        self._schedule_copy(
            path,
            copied_message="Copied path",
            task_name="sase-preview-copy-path",
        )

    def _schedule_copy(
        self,
        value: str,
        *,
        copied_message: str,
        task_name: str,
    ) -> None:
        async def copy_value() -> None:
            try:
                copied = await asyncio.to_thread(copy_to_system_clipboard, value)
            except Exception as exc:
                self.notify(f"Unable to copy: {exc}", severity="error")
                return
            self.notify(
                copied_message
                if copied
                else "Copy failed — clipboard tool not available",
                severity="information" if copied else "error",
            )

        spawn_pump_free_task(
            self,
            copy_value(),
            name=task_name,
            registry_attr="_pump_free_async_tasks",
        )

    def action_open_in_editor(self) -> None:
        path = self._payload.source_path
        if path is None:
            self.notify(
                "This preview does not have a file to edit",
                severity="warning",
            )
            return
        editor = os.environ.get("EDITOR") or "nvim"
        editor_args = build_editor_args(editor, [path])
        with suspend_for_external_tool(
            self.app,
            action="preview_open_editor",
            tool_kind="editor",
            command=editor_args[0],
            path_count=1,
        ):
            subprocess.run(editor_args, check=False)

    def action_open_in_viewer(self) -> None:
        path = self._payload.source_path
        if path is None:
            self.notify(
                "This preview does not have a file to view",
                severity="warning",
            )
            return
        open_artifact_path(self.app, path)

    def action_scroll_down(self) -> None:
        scroll = self.query_one("#preview-scroll", VerticalScroll)
        height = max(1, scroll.scrollable_content_region.height // 2)
        scroll.scroll_relative(y=height, animate=False)

    def action_scroll_up(self) -> None:
        scroll = self.query_one("#preview-scroll", VerticalScroll)
        height = max(1, scroll.scrollable_content_region.height // 2)
        scroll.scroll_relative(y=-height, animate=False)

    def action_scroll_line_down(self) -> None:
        scroll = self.query_one("#preview-scroll", VerticalScroll)
        scroll.scroll_relative(y=1, animate=False)

    def action_scroll_line_up(self) -> None:
        scroll = self.query_one("#preview-scroll", VerticalScroll)
        scroll.scroll_relative(y=-1, animate=False)

    def action_scroll_top(self) -> None:
        scroll = self.query_one("#preview-scroll", VerticalScroll)
        scroll.scroll_home(animate=False)

    def action_scroll_bottom(self) -> None:
        scroll = self.query_one("#preview-scroll", VerticalScroll)
        scroll.scroll_end(animate=False)


__all__ = ["PreviewPanelModal"]
