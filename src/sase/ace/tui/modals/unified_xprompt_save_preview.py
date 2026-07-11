"""Preview rendering and loading for the unified xprompt save modal."""

from __future__ import annotations

import asyncio
import difflib
from pathlib import Path
from typing import TYPE_CHECKING, Literal

from rich.syntax import Syntax
from textual.containers import VerticalScroll
from textual.widgets import Static

from sase.ace.tui.util.debounce import DetailPanelDebouncer
from sase.xprompt.config_yaml import generate_xprompt_yaml
from sase.xprompt.naming import markdown_save_plan
from sase.xprompt.prompt_frontmatter import PromptFrontmatter
from sase.xprompt.save import build_markdown_xprompt
from sase.xprompt.save_index import DefinitionKind
from sase.xprompt.snippet_config_yaml import generate_snippet_yaml

from .unified_xprompt_save_support import SaveMode, UnifiedSaveLocation

PreviewTab = Literal["draft", "existing", "diff"]

if TYPE_CHECKING:
    from textual.screen import ModalScreen as _MixinBase
else:
    _MixinBase = object


class UnifiedXPromptSavePreviewMixin(_MixinBase):
    """Render draft/existing/diff tabs and load existing definitions."""

    if TYPE_CHECKING:
        _body: str
        _existing_cache: dict[tuple[SaveMode, str, str], str]
        _frontmatter: PromptFrontmatter
        _mode: SaveMode
        _preview_debouncer: DetailPanelDebouncer | None
        _preview_tab: PreviewTab
        _preview_tasks: set[asyncio.Task[None]]
        _snippet_body: str

        def _collides(self, row: UnifiedSaveLocation, name: str) -> bool: ...
        def _current_collision(self) -> bool: ...
        def _current_name(self) -> str: ...
        def _disarm(self) -> None: ...
        def _identity(self) -> tuple[SaveMode, str, str] | None: ...
        def _load_definition(
            self, kind: DefinitionKind, path: str, definition_name: str
        ) -> str: ...
        def _prepared_frontmatter(self) -> PromptFrontmatter: ...
        def _refresh(self) -> None: ...
        def _selected_row(self) -> UnifiedSaveLocation | None: ...
        def _short_path(self, path: str) -> str: ...
        def _storage_name(self, row: UnifiedSaveLocation, name: str) -> str: ...
        def _target_path(self, row: UnifiedSaveLocation, name: str) -> str: ...
        def _validation_error(self) -> str | None: ...

    def action_cycle_preview(self) -> None:
        self._disarm()
        tabs: tuple[PreviewTab, ...] = (
            ("draft", "existing", "diff") if self._current_collision() else ("draft",)
        )
        self._preview_tab = (
            tabs[(tabs.index(self._preview_tab) + 1) % len(tabs)]
            if self._preview_tab in tabs
            else tabs[0]
        )
        self._refresh()

    def action_scroll_preview_down(self) -> None:
        scroll = self.query_one("#unified-save-preview-scroll", VerticalScroll)
        scroll.scroll_relative(
            y=max(1, scroll.scrollable_content_region.height // 2), animate=False
        )

    def action_scroll_preview_up(self) -> None:
        scroll = self.query_one("#unified-save-preview-scroll", VerticalScroll)
        scroll.scroll_relative(
            y=-max(1, scroll.scrollable_content_region.height // 2), animate=False
        )

    def _refresh_preview(self) -> None:
        header = self.query_one("#unified-save-preview-header", Static)
        preview = self.query_one("#unified-save-preview", Static)
        row = self._selected_row()
        error = self._validation_error()
        if row is None or error is not None:
            header.update("Preview")
            preview.update("Select a writable destination and enter a valid name.")
            return
        name = self._current_name()
        collision = self._collides(row, name)
        if not collision:
            self._preview_tab = "draft"
        target = self._target_path(row, name)
        action = (
            "Overwrite"
            if collision
            else ("Insert into" if row.location.location_type == "config" else "Create")
        )
        tabs = []
        for tab in ("draft", "existing", "diff"):
            label = tab.title()
            if tab == self._preview_tab:
                tabs.append(f"[{label}]")
            elif collision or tab == "draft":
                tabs.append(label)
            else:
                tabs.append(f"({label})")
        header.update(f"{action} {self._short_path(target)}    " + " · ".join(tabs))
        draft = self._draft_text(row, name)
        if self._preview_tab == "draft":
            preview.update(
                Syntax(
                    draft, self._draft_lexer(row), theme="ansi_dark", word_wrap=False
                )
            )
            return
        identity = self._identity()
        existing = self._existing_cache.get(identity) if identity is not None else None
        if existing is None:
            preview.update("Loading existing definition…")
            self._schedule_existing(row, name, identity)
            return
        if self._preview_tab == "existing":
            preview.update(
                Syntax(
                    existing, self._draft_lexer(row), theme="ansi_dark", word_wrap=False
                )
            )
            return
        diff = "".join(
            difflib.unified_diff(
                existing.splitlines(keepends=True),
                draft.splitlines(keepends=True),
                fromfile=f"a/{Path(target).name}",
                tofile=f"b/{Path(target).name}",
            )
        )
        preview.update(
            Syntax(diff or "(no changes)\n", "diff", theme="ansi_dark", word_wrap=False)
        )

    def _draft_text(self, row: UnifiedSaveLocation, name: str) -> str:
        if self._mode == "snippet":
            return (
                "\n".join(
                    [
                        "ace:",
                        "  snippets:",
                        *generate_snippet_yaml(name, self._snippet_body),
                    ]
                )
                + "\n"
            )
        frontmatter = self._prepared_frontmatter()
        storage_name = self._storage_name(row, name)
        if row.location.location_type == "directory":
            _, frontmatter = markdown_save_plan(storage_name, frontmatter)
            return build_markdown_xprompt(frontmatter, self._body)
        return (
            "\n".join(
                [
                    "xprompts:",
                    *generate_xprompt_yaml(
                        storage_name, [], self._body, frontmatter=frontmatter
                    ),
                ]
            )
            + "\n"
        )

    def _draft_lexer(self, row: UnifiedSaveLocation) -> str:
        return (
            "markdown"
            if self._mode == "xprompt" and row.location.location_type == "directory"
            else "yaml"
        )

    def _schedule_existing(
        self,
        row: UnifiedSaveLocation,
        name: str,
        identity: tuple[SaveMode, str, str] | None,
    ) -> None:
        if identity is None or self._preview_debouncer is None:
            return

        def start() -> None:
            task = asyncio.create_task(self._load_existing(row, name, identity))
            self._preview_tasks.add(task)
            task.add_done_callback(self._preview_tasks.discard)

        self._preview_debouncer.schedule(start)

    async def _load_existing(
        self,
        row: UnifiedSaveLocation,
        name: str,
        identity: tuple[SaveMode, str, str],
    ) -> None:
        mode = identity[0]
        kind: DefinitionKind
        if mode == "snippet":
            kind = "snippet_config"
            path = row.location.path
        elif row.location.location_type == "config":
            kind = "xprompt_config"
            path = row.location.path
        else:
            kind = "markdown"
            filename, _ = markdown_save_plan(
                self._storage_name(row, name), self._prepared_frontmatter()
            )
            path = str(Path(row.location.path) / filename)
        try:
            definition_name = self._storage_name(row, name)
            existing = await asyncio.to_thread(
                self._load_definition, kind, path, definition_name
            )
        except Exception as exc:
            existing = f"(preview unavailable: {exc})\n"
        if self.is_mounted and self._identity() == identity:
            self._existing_cache[identity] = existing
            self._refresh_preview()


__all__ = ["PreviewTab", "UnifiedXPromptSavePreviewMixin"]
