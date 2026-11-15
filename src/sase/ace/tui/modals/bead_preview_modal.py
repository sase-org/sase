"""Purpose-built bead preview modal."""

from __future__ import annotations

import asyncio

from rich.console import Group, RenderableType
from rich.text import Text
from textual.app import ComposeResult
from textual.containers import Container, VerticalScroll
from textual.css.query import NoMatches
from textual.screen import ModalScreen
from textual.widgets import Markdown, Static

from sase.ace.tui.actions.clipboard import schedule_copy_delivery
from sase.ace.tui.models.bead_preview import (
    BeadPreview,
    BeadStoreRef,
    load_bead_preview,
)
from sase.bead.model import Issue
from sase.pager.beads import bead_detail_link_resolution
from sase.pager.link_context import LinkAnchor, LinkResolutionContext
from sase.pager.targets import LinkResolution

from ._source_file_actions import SourceFileActionsMixin
from .base import CopyModeForwardingMixin
from .bead_preview_render import (
    BeadCardPalette,
    bead_card_palette,
    bead_description_markdown,
    build_bead_loading_title,
    build_bead_meta,
    build_bead_related,
    build_bead_title,
    children_are_phases,
    numbered_child_count,
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
        ("r", "reload", "Reload"),
        ("p", "open_parent", "Parent"),
        ("backspace", "go_back", "Back"),
        ("enter", "open_detail", "Open detail"),
        ("ctrl+d", "scroll_down", "Scroll down"),
        ("ctrl+u", "scroll_up", "Scroll up"),
        ("j", "scroll_line_down", "Line down"),
        ("k", "scroll_line_up", "Line up"),
        ("g", "scroll_top", "Top"),
        ("G", "scroll_bottom", "Bottom"),
        ("shift+g", "scroll_bottom", "Bottom"),
        *(
            (str(index), f"follow_child({index})", f"Child {index}")
            for index in range(1, 10)
        ),
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
        self._detail_request_id = 0
        self._history: list[tuple[str, BeadPreview | None]] = []
        self._accent = _FALLBACK_ACCENT
        self._palette: BeadCardPalette | None = None
        self._paint_generation = 0

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

    def on_unmount(self) -> None:
        self._invalidate_requests()

    def action_close(self) -> None:
        self._invalidate_requests()
        self.dismiss(None)

    def action_copy_id(self) -> None:
        schedule_copy_delivery(
            self,
            self._bead_id,
            copied_label="bead ID",
            task_name="sase-bead-preview-copy-id",
        )

    def action_retry(self) -> None:
        self.action_reload()

    def action_reload(self) -> None:
        self._invalidate_requests()
        self._error = None
        self._preview = None
        self._start_load()
        self.run_worker(
            self._refresh_widgets(reset_scroll=True),
            name="bead-preview-reload-paint",
        )

    def action_follow_child(self, number: int) -> None:
        index = int(number) - 1
        children = self._children()
        if index < 0 or index >= numbered_child_count(children):
            return
        self._navigate_to(children[index].id)

    def action_open_parent(self) -> None:
        parent_id = self._parent_id()
        if parent_id is None:
            return
        self._navigate_to(parent_id)

    def action_go_back(self) -> None:
        if not self._history:
            return
        self._invalidate_requests()
        bead_id, preview = self._history.pop()
        self._bead_id = bead_id
        self._preview = preview
        self._error = None
        if preview is None:
            self._start_load()
        self.run_worker(
            self._refresh_widgets(reset_scroll=True),
            name="bead-preview-back-paint",
        )

    def action_open_detail(self) -> None:
        if self._preview is None:
            return
        self._detail_request_id += 1
        request_id = self._detail_request_id
        bead_id = self._bead_id
        load_request_id = self._load_request_id
        self.run_worker(
            self._open_detail_async(request_id, bead_id, load_request_id),
            name=f"bead-preview-detail:{request_id}",
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
        bead_id = self._bead_id
        self.run_worker(
            self._load_preview_async(request_id, bead_id),
            name=f"bead-preview-load:{request_id}",
        )

    def _navigate_to(self, bead_id: str) -> None:
        if bead_id == self._bead_id and self._error is None:
            return
        self._invalidate_requests()
        self._history.append((self._bead_id, self._preview))
        self._bead_id = bead_id
        self._preview = None
        self._error = None
        self._start_load()
        self.run_worker(
            self._refresh_widgets(reset_scroll=True),
            name="bead-preview-navigate-paint",
        )

    async def _load_preview_async(self, request_id: int, bead_id: str) -> None:
        try:
            preview = await asyncio.to_thread(
                load_bead_preview,
                bead_id,
                self._store,
            )
        except Exception as exc:
            if not self._load_is_current(request_id, bead_id):
                return
            self._error = str(exc) or exc.__class__.__name__
            self._preview = None
            await self._refresh_widgets(
                reset_scroll=True,
                bead_id=bead_id,
                generation=self._paint_generation,
            )
            return
        if not self._load_is_current(request_id, bead_id):
            return
        self._preview = preview
        self._error = None
        if not self._load_is_current(request_id, bead_id):
            return
        self._seed_bead_mention(preview)
        await self._refresh_widgets(
            reset_scroll=True,
            bead_id=bead_id,
            generation=self._paint_generation,
        )

    def _seed_bead_mention(self, preview: BeadPreview) -> None:
        """Seed the prompt mention index with the just-loaded status."""
        try:
            app = self.app
        except Exception:
            return
        seeder = getattr(app, "seed_bead_mention_status", None)
        if not callable(seeder):
            return
        try:
            status = preview.issue.status.value
        except Exception:
            status = None
        if not isinstance(status, str) or not status:
            return
        try:
            seeder(
                preview.issue.id,
                status,
                store_key=str(self._store.beads_dir),
                fingerprint_token=None,
                project_ref=self._store.project_key or None,
                context_key=(
                    f"store:{self._store.project_key.casefold()}"
                    if self._store.project_key
                    else None
                ),
            )
        except Exception:
            pass

    async def _open_detail_async(
        self,
        request_id: int,
        bead_id: str,
        load_request_id: int,
    ) -> None:
        try:
            resolution = await asyncio.to_thread(self._resolve_current_detail, bead_id)
        except Exception as exc:  # noqa: BLE001 - card enter must not crash
            if not self._detail_is_current(request_id, bead_id, load_request_id):
                return
            self.notify(str(exc) or exc.__class__.__name__, severity="warning")
            return
        if not self._detail_is_current(request_id, bead_id, load_request_id):
            return
        self._present_detail(resolution, bead_id=bead_id)

    def _resolve_current_detail(self, bead_id: str) -> LinkResolution:
        return bead_detail_link_resolution(
            bead_id,
            project_ref=self._store.project_key or None,
            context=LinkResolutionContext(
                anchors=(LinkAnchor(self._store.primary_workspace),)
            ),
        )

    def _present_detail(self, resolution: LinkResolution, *, bead_id: str) -> None:
        document = resolution.target.document if resolution.target is not None else None
        if document is None:
            message = resolution.unresolved_message or (
                f"bead:{bead_id} could not be resolved"
            )
            self.notify(message, severity="warning")
            return
        from sase.pager.screen import PagerScreen

        self.app.push_screen(PagerScreen(document, links_enabled=True))

    def _invalidate_requests(self) -> None:
        self._load_request_id += 1
        self._detail_request_id += 1
        self._paint_generation += 1

    def _load_is_current(self, request_id: int, bead_id: str) -> bool:
        return (
            request_id == self._load_request_id
            and bead_id == self._bead_id
            and self.is_attached
        )

    def _detail_is_current(
        self,
        request_id: int,
        bead_id: str,
        load_request_id: int,
    ) -> bool:
        return (
            request_id == self._detail_request_id
            and load_request_id == self._load_request_id
            and bead_id == self._bead_id
            and self.is_attached
        )

    def _breadcrumb(self) -> str | None:
        if not self._history:
            return None
        return self._history[-1][0]

    def _children(self) -> tuple[Issue, ...]:
        if self._preview is None:
            return ()
        return self._preview.children

    def _parent_id(self) -> str | None:
        if self._preview is None:
            return None
        if self._preview.ancestors:
            ancestor = self._preview.ancestors[0]
            if ancestor is not None:
                return ancestor.id
        parent_id = self._preview.issue.parent_id
        return parent_id or None

    def _build_title(self) -> RenderableType:
        palette = self._palette
        breadcrumb = self._breadcrumb()
        if self._preview is not None and palette is not None:
            return build_bead_title(
                self._preview.issue,
                project_label=self._store.project_label,
                palette=palette,
                children=self._preview.children,
                breadcrumb=breadcrumb,
            )
        accent = self._accent
        if palette is not None:
            accent = palette.plan
        return build_bead_loading_title(
            self._bead_id,
            project_label=self._store.project_label,
            accent=accent,
            breadcrumb=breadcrumb,
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
        sections: list[RenderableType] = []
        related = None
        if self._palette is not None:
            related = build_bead_related(self._preview, palette=self._palette)
        if related is not None:
            sections.append(related)
        sections.append(Text("-" * 66, style="dim"))
        sections.append(build_bead_meta(self._preview, accent=self._accent))
        return Group(*sections)

    def _build_footer(self) -> str:
        parts = ["j/k"]
        parts.append("y id")
        if self._preview is not None:
            parts.append("⏎ detail")
            child_count = numbered_child_count(self._children())
            if child_count:
                kind = "phase" if children_are_phases(self._preview.issue) else "child"
                if child_count == 1:
                    parts.append(f"1 {kind}")
                else:
                    parts.append(f"1-{child_count} {kind}")
            if self._parent_id() is not None:
                parts.append("p parent")
        if self._history:
            parts.append("⌫ back")
        if self._source_action_path():
            parts.extend(("Y path", "o edit", "Z view"))
        if self._error is not None:
            parts.append("r retry")
        else:
            parts.append("r reload")
        parts.append("esc")
        return " | ".join(parts)

    async def _refresh_widgets(
        self,
        *,
        reset_scroll: bool,
        bead_id: str | None = None,
        generation: int | None = None,
    ) -> None:
        bead_id = self._bead_id if bead_id is None else bead_id
        generation = self._paint_generation if generation is None else generation
        if not self._paint_is_current(bead_id, generation):
            return
        if not self.is_attached:
            return
        try:
            title = self.query_one("#bead-preview-title", Static)
            status = self.query_one("#bead-preview-status", Static)
            description = self.query_one("#bead-preview-description", Markdown)
            meta = self.query_one("#bead-preview-meta", Static)
            footer = self.query_one("#bead-preview-footer", Static)
            scroll = self.query_one("#bead-preview-scroll", VerticalScroll)
        except NoMatches:
            if self.is_attached:
                self.call_after_refresh(
                    lambda: self.run_worker(
                        self._refresh_widgets(
                            reset_scroll=reset_scroll,
                            bead_id=bead_id,
                            generation=generation,
                        ),
                        name="bead-preview-paint-retry",
                    )
                )
            return
        title.update(self._build_title())
        status.update(self._build_status())
        await description.update(self._description_markdown())
        if not self._paint_is_current(bead_id, generation):
            return
        meta.update(self._build_meta())
        footer.update(self._build_footer())
        if reset_scroll:
            scroll.scroll_home(animate=False)

    def _paint_is_current(self, bead_id: str, generation: int) -> bool:
        return (
            self.is_attached
            and self._bead_id == bead_id
            and self._paint_generation == generation
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
