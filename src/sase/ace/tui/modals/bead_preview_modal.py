"""Purpose-built bead preview modal."""

from __future__ import annotations

import asyncio

from rich.console import Group, RenderableType
from rich.text import Text
from textual.app import ComposeResult
from textual.containers import Container, VerticalScroll
from textual.screen import ModalScreen
from textual.widgets import Markdown, Static

from sase.ace.tui.actions.clipboard import schedule_copy_delivery
from sase.ace.tui.models.bead_preview import (
    BeadPreview,
    BeadStoreRef,
    load_bead_preview,
)

from ._source_file_actions import SourceFileActionsMixin
from .base import CopyModeForwardingMixin
from .bead_preview_render import (
    BeadCardPalette,
    bead_card_palette,
    bead_description_markdown,
    build_bead_loading_title,
    build_bead_meta,
    build_bead_title,
)

_FALLBACK_ACCENT = "#FFD700"
_LOADING_BODY = "Loading…"


class BeadPreviewModal(
    CopyModeForwardingMixin,
    SourceFileActionsMixin,
    ModalScreen[None],
):
    """Display one bead as a structured preview card."""

    BINDINGS = [
        ("escape", "close", "Close"),
        ("q", "close", "Close"),
        ("y", "copy_id", "Copy ID"),
        ("Y", "copy_path", "Copy path"),
        ("shift+y", "copy_path", "Copy path"),
        ("o", "open_in_editor", "Open in editor"),
        ("Z", "open_in_viewer", "Open in viewer"),
        ("shift+z", "open_in_viewer", "Open in viewer"),
        ("r", "retry", "Retry"),
        ("ctrl+d", "scroll_down", "Scroll down"),
        ("ctrl+u", "scroll_up", "Scroll up"),
        ("j", "scroll_line_down", "Line down"),
        ("k", "scroll_line_up", "Line up"),
        ("g", "scroll_top", "Top"),
        ("G", "scroll_bottom", "Bottom"),
        ("shift+g", "scroll_bottom", "Bottom"),
    ]

    def __init__(
        self,
        store: BeadStoreRef,
        bead_id: str,
        *,
        preview: BeadPreview | None = None,
    ) -> None:
        super().__init__()
        self._store = store
        self._bead_id = bead_id
        self._preview = preview
        self._error: str | None = None
        self._load_request_id = 0
        self._accent = _FALLBACK_ACCENT
        self._palette: BeadCardPalette | None = None

    def compose(self) -> ComposeResult:
        self._palette = bead_card_palette(self.app.current_theme)
        self._accent = self._palette.plan
        with Container(id="bead-preview-container"):
            yield Static(self._build_title(), id="bead-preview-title")
            with VerticalScroll(id="bead-preview-scroll"):
                yield Static(self._build_status(), id="bead-preview-status")
                yield Markdown(
                    self._description_markdown(),
                    id="bead-preview-description",
                )
                yield Static(self._build_meta(), id="bead-preview-meta")
            yield Static(self._build_footer(), id="bead-preview-footer")

    def on_mount(self) -> None:
        if self._preview is None and self._error is None:
            self._start_load()

    def action_close(self) -> None:
        self.dismiss(None)

    def action_copy_id(self) -> None:
        schedule_copy_delivery(
            self,
            self._bead_id,
            copied_label="bead ID",
            task_name="sase-bead-preview-copy-id",
        )

    def action_retry(self) -> None:
        if self._error is None:
            return
        self._error = None
        self._preview = None
        self._start_load()
        self.run_worker(
            self._refresh_widgets(reset_scroll=True),
            name="bead-preview-retry-paint",
        )

    def _source_action_path(self) -> str | None:
        if self._preview is None:
            return None
        return self._preview.plan_path

    def _source_action_position(self) -> tuple[int | None, int | None]:
        return None, None

    def _start_load(self) -> None:
        self._load_request_id += 1
        request_id = self._load_request_id
        self.run_worker(
            self._load_preview_async(request_id),
            name=f"bead-preview-load:{request_id}",
        )

    async def _load_preview_async(self, request_id: int) -> None:
        try:
            preview = await asyncio.to_thread(
                load_bead_preview,
                self._bead_id,
                self._store,
            )
        except Exception as exc:
            if not self._load_is_current(request_id):
                return
            self._error = str(exc) or exc.__class__.__name__
            self._preview = None
            await self._refresh_widgets(reset_scroll=True)
            return
        if not self._load_is_current(request_id):
            return
        self._preview = preview
        self._error = None
        await self._refresh_widgets(reset_scroll=True)

    def _load_is_current(self, request_id: int) -> bool:
        return request_id == self._load_request_id and self.is_attached

    def _build_title(self) -> RenderableType:
        palette = self._palette
        if self._preview is not None and palette is not None:
            return build_bead_title(
                self._preview.issue,
                project_label=self._store.project_label,
                palette=palette,
            )
        accent = self._accent
        if palette is not None:
            accent = palette.plan
        return build_bead_loading_title(
            self._bead_id,
            project_label=self._store.project_label,
            accent=accent,
        )

    def _build_status(self) -> RenderableType:
        if self._error:
            return Text(self._error, style="bold red")
        if self._preview is None:
            return Text(_LOADING_BODY, style="dim")
        return Text("")

    def _description_markdown(self) -> str:
        if self._preview is None:
            return ""
        body = bead_description_markdown(self._preview.issue)
        if body:
            return body
        return "_No description._"

    def _build_meta(self) -> RenderableType:
        if self._preview is None:
            return Text("")
        sections: list[RenderableType] = [
            Text("-" * 66, style="dim"),
            build_bead_meta(self._preview, accent=self._accent),
        ]
        return Group(*sections)

    def _build_footer(self) -> str:
        parts = ["j/k"]
        parts.append("y id")
        if self._source_action_path():
            parts.extend(("Y path", "o edit", "Z view"))
        if self._error is not None:
            parts.append("r retry")
        parts.append("esc")
        return " | ".join(parts)

    async def _refresh_widgets(self, *, reset_scroll: bool) -> None:
        if not self.is_attached:
            return
        self.query_one("#bead-preview-title", Static).update(self._build_title())
        self.query_one("#bead-preview-status", Static).update(self._build_status())
        description = self.query_one("#bead-preview-description", Markdown)
        await description.update(self._description_markdown())
        self.query_one("#bead-preview-meta", Static).update(self._build_meta())
        self.query_one("#bead-preview-footer", Static).update(self._build_footer())
        if reset_scroll:
            self.query_one("#bead-preview-scroll", VerticalScroll).scroll_home(
                animate=False
            )

    def action_scroll_down(self) -> None:
        scroll = self.query_one("#bead-preview-scroll", VerticalScroll)
        height = max(1, scroll.scrollable_content_region.height // 2)
        scroll.scroll_relative(y=height, animate=False)

    def action_scroll_up(self) -> None:
        scroll = self.query_one("#bead-preview-scroll", VerticalScroll)
        height = max(1, scroll.scrollable_content_region.height // 2)
        scroll.scroll_relative(y=-height, animate=False)

    def action_scroll_line_down(self) -> None:
        scroll = self.query_one("#bead-preview-scroll", VerticalScroll)
        scroll.scroll_relative(y=1, animate=False)

    def action_scroll_line_up(self) -> None:
        scroll = self.query_one("#bead-preview-scroll", VerticalScroll)
        scroll.scroll_relative(y=-1, animate=False)

    def action_scroll_top(self) -> None:
        scroll = self.query_one("#bead-preview-scroll", VerticalScroll)
        scroll.scroll_home(animate=False)

    def action_scroll_bottom(self) -> None:
        scroll = self.query_one("#bead-preview-scroll", VerticalScroll)
        scroll.scroll_end(animate=False)


__all__ = ["BeadPreviewModal"]
