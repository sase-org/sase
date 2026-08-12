"""Scrollable syntax-highlighted preview modal."""

from __future__ import annotations

import asyncio
from typing import Literal, cast

from rich.console import RenderableType
from rich.text import Text
from textual import events
from textual.app import ComposeResult
from textual.containers import Container, VerticalScroll
from textual.screen import ModalScreen
from textual.widgets import Input, Markdown, Static
from textual.worker import Worker, WorkerState

from sase.ace.tui.actions.clipboard import schedule_copy_delivery
from sase.ace.tui.util.lazy_syntax import (
    LazySyntaxRenderCache,
    exceeds_plain_render_cap,
    lazy_renderable,
)
from sase.ace.tui.util.pump_tasks import (
    cancel_pump_free_tasks,
    spawn_pump_free_task,
)
from sase.ace.tui.widgets._prompt_preview_target import PreviewPayload

from ._source_file_actions import SourceFileActionsMixin
from .base import CopyModeForwardingMixin, FilterInput
from .preview_properties_render import build_properties_band, build_properties_view
from .preview_search import PreviewSearchResult, build_search_result


_COLOR_MUTED = "dim #87D7FF"
_ViewMode = Literal["source", "rendered", "properties"]


class _PreviewSearchInput(FilterInput):
    """Search input that gives escape back to the preview reader."""

    BINDINGS = [
        *FilterInput.BINDINGS,
        ("escape", "cancel_preview_search", "Cancel search"),
    ]

    def action_cancel_preview_search(self) -> None:
        modal = self.screen
        if isinstance(modal, PreviewPanelModal):
            modal._hide_search_input()  # noqa: SLF001


def _fence_leading_yaml_frontmatter(content: str) -> str:
    """Fence a leading YAML frontmatter block for Textual Markdown rendering."""
    lines = content.splitlines(keepends=True)
    if not lines or lines[0].strip() != "---":
        return content
    for index, line in enumerate(lines[1:], start=1):
        if line.strip() != "---":
            continue
        frontmatter = "".join(lines[: index + 1])
        body = "".join(lines[index + 1 :])
        return f"```yaml\n{frontmatter}```\n{body}"
    return content


class PreviewPanelModal(
    CopyModeForwardingMixin,
    SourceFileActionsMixin,
    ModalScreen[None],
):
    """Presentational modal for resolved xprompt/file previews and their properties."""

    BINDINGS = [
        ("escape", "escape", "Clear search / close"),
        ("q", "close", "Close"),
        ("/", "open_search", "Search"),
        ("n", "next_match", "Next match"),
        ("N", "previous_match", "Previous match"),
        ("shift+n", "previous_match", "Previous match"),
        ("y", "copy_contents", "Copy contents"),
        ("Y", "copy_path", "Copy path"),
        ("shift+y", "copy_path", "Copy path"),
        ("R", "toggle_rendered", "Rendered / source"),
        ("shift+r", "toggle_rendered", "Rendered / source"),
        ("p", "toggle_properties", "Properties view"),
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
        self._view_mode: _ViewMode = "source"
        self._previous_view_mode: _ViewMode = "source"
        self._properties_band: RenderableType | None = (
            build_properties_band(payload.properties)
            if payload.properties is not None
            else None
        )
        self._properties_view: RenderableType | None = (
            build_properties_view(payload.properties)
            if payload.properties is not None
            else None
        )
        self._rendered_ready = False
        self._rendered_content: str | None = None
        self._requested_rendered = (
            payload.default_view == "rendered" and self._can_render_markdown()
        )
        self._render_task: asyncio.Task[None] | None = None
        self._search_query = ""
        self._match_lines: tuple[int, ...] = ()
        self._match_index: int | None = None
        self._row_offsets_by_width: dict[int, tuple[int, ...]] = {}
        self._displayed_line_count = max(1, payload.content.count("\n") + 1)
        self._search_worker: Worker[PreviewSearchResult] | None = None
        self._search_identity: tuple[int, str, int] | None = None
        self._search_serial = 0
        self._search_viewport_row = 0
        self._pending_match_delta: int | None = None

    def compose(self) -> ComposeResult:
        with Container(id="preview-modal-container"):
            yield Static(self._build_title(), id="preview-title")
            band = Static(self._properties_band or "", id="preview-properties")
            band.display = self._properties_band is not None
            yield band
            with VerticalScroll(id="preview-scroll"):
                yield Static(self._build_content(), id="preview-content")
                rendered = Markdown("", id="preview-rendered")
                rendered.display = False
                yield rendered
                properties_view = Static(
                    self._properties_view or "",
                    id="preview-properties-view",
                )
                properties_view.display = False
                yield properties_view
            search_input = _PreviewSearchInput(
                placeholder="Search source (smartcase)",
                id="preview-search-input",
            )
            search_input.display = False
            yield search_input
            yield Static(self._build_footer(), id="preview-footer")

    def on_mount(self) -> None:
        if self._requested_rendered:
            self._schedule_rendered_update()

    def on_unmount(self) -> None:
        self._cancel_search_worker()
        cancel_pump_free_tasks(self)

    def on_key(self, event: events.Key) -> None:
        if isinstance(self.focused, _PreviewSearchInput):
            return
        super().on_key(event)

    def on_input_submitted(self, event: Input.Submitted) -> None:
        if event.input.id != "preview-search-input":
            return
        event.stop()
        query = event.value
        self._hide_search_input()
        if not query:
            self._clear_search()
            return
        self._start_search(query)

    def on_worker_state_changed(self, event: Worker.StateChanged) -> None:
        if event.worker is not self._search_worker:
            return
        if event.state not in {
            WorkerState.SUCCESS,
            WorkerState.ERROR,
            WorkerState.CANCELLED,
        }:
            return
        identity = self._search_identity
        self._search_worker = None
        if event.state != WorkerState.SUCCESS or identity is None:
            return
        serial, query, width = identity
        if serial != self._search_serial or query != self._search_query:
            return
        current_width = self._source_width()
        if width != current_width:
            self._start_search(query, preserve_matches=True)
            return
        result = cast(PreviewSearchResult, event.worker.result)
        self._row_offsets_by_width[width] = result.row_offsets
        self._displayed_line_count = result.displayed_line_count
        self._match_lines = result.match_lines
        if self._pending_match_delta is not None and self._match_lines:
            current = self._match_index if self._match_index is not None else 0
            self._match_index = (current + self._pending_match_delta) % len(
                self._match_lines
            )
            self._pending_match_delta = None
        else:
            self._pending_match_delta = None
            self._match_index = self._match_at_or_after_viewport(
                result,
                self._search_viewport_row,
            )
        if not self.is_attached:
            return
        self.query_one("#preview-content", Static).update(self._build_content())
        self.query_one("#preview-footer", Static).update(self._build_footer())
        self._jump_to_current_match()

    def _build_title(self) -> Text:
        text = Text()
        text.append(self._payload.icon, style="bold #FFD700")
        text.append(" ")
        text.append(self._payload.kind_label.upper(), style="bold #87D7FF")
        if self._view_mode == "properties":
            text.append(" PROPERTIES", style="bold #AFD7FF")
        elif self._is_markdown_payload():
            text.append(f" {self._view_mode.upper()}", style="bold #AFD7FF")
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
            "/ search",
        ]
        if self._search_query:
            if self._match_index is None:
                parts.append(f"0/{len(self._match_lines)}")
            else:
                line_number = self._match_lines[self._match_index]
                parts.append(
                    f"{self._match_index + 1}/{len(self._match_lines)} · "
                    f"line {line_number}"
                )
            parts.append("n/N matches")
        parts.append("y contents")
        if self._is_markdown_payload():
            target = "source" if self._view_mode == "rendered" else "rendered"
            parts.append(f"R {target}")
        if self._properties_available():
            target = "source" if self._view_mode == "properties" else "properties"
            parts.append(f"p {target}")
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
            highlight_lines=frozenset(self._match_lines) or None,
        )

    def _is_markdown_payload(self) -> bool:
        return self._payload.lexer == "markdown"

    def _properties_available(self) -> bool:
        properties = self._payload.properties
        return properties is not None and not properties.is_empty

    def _rendered_markdown_content(self) -> str:
        if self._rendered_content is None:
            self._rendered_content = _fence_leading_yaml_frontmatter(
                self._payload.content
            )
        return self._rendered_content

    def _can_render_markdown(self) -> bool:
        return self._is_markdown_payload() and not exceeds_plain_render_cap(
            self._rendered_markdown_content()
        )

    def _refresh_preview_widgets(self, *, reset_scroll: bool) -> None:
        if not self.is_attached:
            return
        self.query_one("#preview-title", Static).update(self._build_title())
        self.query_one("#preview-footer", Static).update(self._build_footer())
        source = self.query_one("#preview-content", Static)
        rendered = self.query_one("#preview-rendered", Markdown)
        properties_view = self.query_one("#preview-properties-view", Static)
        source.display = self._view_mode == "source"
        rendered.display = self._view_mode == "rendered"
        properties_view.display = self._view_mode == "properties"
        band = self.query_one("#preview-properties", Static)
        band.display = (
            self._properties_band is not None and self._view_mode != "properties"
        )
        if reset_scroll:
            self.query_one("#preview-scroll", VerticalScroll).scroll_home(animate=False)

    def _set_view_mode(self, mode: _ViewMode, *, reset_scroll: bool = True) -> None:
        self._view_mode = mode
        if mode == "source":
            self._requested_rendered = False
        self._refresh_preview_widgets(reset_scroll=reset_scroll)

    def _schedule_rendered_update(self) -> None:
        if self._rendered_ready:
            self._set_view_mode("rendered")
            return
        if self._render_task is not None and not self._render_task.done():
            return

        async def update_rendered() -> None:
            try:
                if not self.is_attached:
                    return
                rendered = self.query_one("#preview-rendered", Markdown)
                await rendered.update(self._rendered_markdown_content())
                if not self.is_attached:
                    return
                self._rendered_ready = True
                if self._requested_rendered:
                    self._set_view_mode("rendered")
            finally:
                self._render_task = None

        self._render_task = spawn_pump_free_task(
            self,
            update_rendered(),
            name="sase-preview-render-markdown",
            registry_attr="_pump_free_async_tasks",
        )

    def action_close(self) -> None:
        self.dismiss(None)

    def action_escape(self) -> None:
        if self._search_query:
            self._clear_search()
            return
        self.action_close()

    def action_open_search(self) -> None:
        if self._view_mode in ("rendered", "properties") or self._requested_rendered:
            self._set_view_mode("source")
        search_input = self.query_one("#preview-search-input", _PreviewSearchInput)
        search_input.value = self._search_query
        search_input.display = True
        search_input.focus()
        search_input.cursor_position = len(search_input.value)

    def _hide_search_input(self) -> None:
        if not self.is_attached:
            return
        search_input = self.query_one("#preview-search-input", _PreviewSearchInput)
        search_input.value = self._search_query
        search_input.display = False
        self.set_focus(None)

    def _source_width(self) -> int:
        if not self.is_attached:
            return 1
        source = self.query_one("#preview-content", Static)
        return max(1, source.content_region.width)

    def _cancel_search_worker(self) -> None:
        if self._search_worker is not None:
            self._search_worker.cancel()
        self._search_worker = None
        self._search_identity = None

    def _start_search(
        self,
        query: str,
        *,
        preserve_matches: bool = False,
    ) -> None:
        self._cancel_search_worker()
        self._search_query = query
        if not preserve_matches:
            self._match_lines = ()
            self._match_index = None
            self._pending_match_delta = None
        self._search_serial += 1
        width = self._source_width()
        scroll = self.query_one("#preview-scroll", VerticalScroll)
        self._search_viewport_row = int(scroll.scroll_y)
        identity = (self._search_serial, query, width)
        self._search_identity = identity
        content = self._payload.content
        lexer = self._payload.lexer
        self._search_worker = self.run_worker(
            lambda: build_search_result(content, query, width, lexer),
            name="preview-search",
            group="preview-search",
            thread=True,
            exclusive=True,
            exit_on_error=False,
        )

    @staticmethod
    def _match_at_or_after_viewport(
        result: PreviewSearchResult,
        viewport_row: int,
    ) -> int | None:
        for match_index, line_number in enumerate(result.match_lines):
            if result.row_offsets[line_number - 1] >= viewport_row:
                return match_index
        return 0 if result.match_lines else None

    def _clear_search(self) -> None:
        self._cancel_search_worker()
        self._search_query = ""
        self._match_lines = ()
        self._match_index = None
        self._pending_match_delta = None
        if not self.is_attached:
            return
        self.query_one("#preview-content", Static).update(self._build_content())
        self.query_one("#preview-footer", Static).update(self._build_footer())

    def action_next_match(self) -> None:
        self._move_match(1)

    def action_previous_match(self) -> None:
        self._move_match(-1)

    def _move_match(self, delta: int) -> None:
        if not self._match_lines:
            return
        if self._view_mode in ("rendered", "properties"):
            self._set_view_mode("source")
        width = self._source_width()
        if width not in self._row_offsets_by_width:
            self._pending_match_delta = delta
            self._start_search(self._search_query, preserve_matches=True)
            return
        current = self._match_index if self._match_index is not None else 0
        self._match_index = (current + delta) % len(self._match_lines)
        self.query_one("#preview-footer", Static).update(self._build_footer())
        self._jump_to_current_match()

    def _jump_to_current_match(self) -> None:
        if self._match_index is None or not self._match_lines:
            return
        line_number = self._match_lines[self._match_index]
        if line_number > self._displayed_line_count:
            self.notify(
                f"Match at line {line_number} is beyond the displayed portion",
                severity="warning",
            )
            return
        offsets = self._row_offsets_by_width.get(self._source_width())
        if offsets is None or line_number > len(offsets):
            return
        scroll = self.query_one("#preview-scroll", VerticalScroll)
        center_offset = max(0, scroll.scrollable_content_region.height // 3)
        scroll.scroll_to(
            y=max(0, offsets[line_number - 1] - center_offset),
            animate=False,
            immediate=True,
        )

    def action_toggle_rendered(self) -> None:
        if not self._is_markdown_payload():
            self.notify(
                "This preview is not Markdown",
                severity="warning",
            )
            return
        if self._view_mode == "rendered" or self._requested_rendered:
            self._set_view_mode("source")
            return
        if exceeds_plain_render_cap(self._rendered_markdown_content()):
            self.notify(
                "This preview is too large to render as Markdown",
                severity="warning",
            )
            return
        self._requested_rendered = True
        if self._rendered_ready:
            self._set_view_mode("rendered")
        else:
            self._schedule_rendered_update()

    def action_toggle_properties(self) -> None:
        if not self._properties_available():
            self.notify(
                "This preview has no xprompt properties",
                severity="warning",
            )
            return
        if self._view_mode == "properties":
            self._set_view_mode(self._previous_view_mode)
            return
        self._previous_view_mode = self._view_mode
        self._set_view_mode("properties")

    def action_copy_contents(self) -> None:
        self._schedule_copy(
            self._payload.content,
            copied_message=f"Copied {self._payload.kind_label} contents",
            task_name="sase-preview-copy-contents",
        )

    def _schedule_copy(
        self,
        value: str,
        *,
        copied_message: str,
        task_name: str,
    ) -> None:
        schedule_copy_delivery(
            self,
            value,
            copied_label=copied_message.removeprefix("Copied "),
            task_name=task_name,
        )

    def _source_action_path(self) -> str | None:
        return self._payload.source_path

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
