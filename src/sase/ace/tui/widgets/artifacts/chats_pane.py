"""Empty shell for the Artifacts chats pane."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from rich.text import Text
from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.widgets import Static

from sase.ace.tui.keymaps import (
    KeymapRegistry,
    key_display_name,
    load_keymap_registry,
)

from .entry_navigation import ArtifactEntryTarget
from .lifecycle import ArtifactsPaneLifecycle
from .types import ARTIFACTS_ACCENTS


class ArtifactsChatsPane(ArtifactsPaneLifecycle, Vertical):
    """Host the Chats layout while catalog-backed rows land separately."""

    can_focus = False

    def __init__(self, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self._init_artifacts_lifecycle()
        self.project_scope: str | None = None
        self._project_display_name: str | None = None
        self._registry = load_keymap_registry({})

    def compose(self) -> ComposeResult:
        yield Static("", id="chats-filter-bar", classes="hidden")
        yield Static(
            self._scope_text(),
            classes="artifacts-pane-info",
            id="chats-info",
        )
        with Horizontal(id="chats-panels"):
            list_panel = Vertical(id="chats-list-panel")
            list_panel.border_title = "Chats"
            with list_panel:
                yield Static("No chat transcripts found.", id="chats-empty")
            detail_panel = Vertical(id="chats-detail-panel")
            detail_panel.border_title = "Details"
            with detail_panel:
                with VerticalScroll(id="chats-detail-scroll"):
                    yield Static("", id="chats-detail")
        yield Static(self._hints_text(), id="chats-hints")

    def set_keymap_registry(self, registry: KeymapRegistry) -> None:
        """Use the active registry for pane-scoped key hints."""
        self._registry = registry
        self._update_static("#chats-info", self._scope_text())
        self._update_static("#chats-hints", self._hints_text())

    def set_project_scope(
        self,
        project: str | None,
        *,
        display_name: str | None = None,
    ) -> None:
        """Update the shared project scope without loading chat data."""
        self.project_scope = project
        self._project_display_name = display_name
        self._update_static("#chats-info", self._scope_text())

    def _update_static(self, selector: str, content: Text) -> None:
        if self.is_mounted:
            self.query_one(selector, Static).update(content)

    def _scope_text(self) -> Text:
        accent = ARTIFACTS_ACCENTS["chats"]
        scope = self._project_display_name or self.project_scope or "All projects"
        text = Text()
        text.append(" Chats ", style=f"bold #1a1a1a on {accent}")
        text.append("  Project scope  ", style="dim")
        text.append(f" {scope} ", style=f"bold {accent}")
        text.append("  ·  ", style="dim")
        text.append(
            f"{key_display_name(self._registry.app.pick_artifacts_project)} change",
            style="dim",
        )
        return text

    def _hints_text(self) -> Text:
        keymap = self._registry.app
        text = Text(justify="center")
        hints = (
            (key_display_name(keymap.chats_next), "next"),
            (key_display_name(keymap.chats_prev), "previous"),
            (key_display_name(keymap.chats_view_selected), "view"),
            (key_display_name(keymap.chats_filters), "filter"),
            (key_display_name(keymap.chats_refresh), "refresh"),
        )
        for index, (key, label) in enumerate(hints):
            if index:
                text.append("  ·  ", style="dim")
            text.append(key, style=f"bold {ARTIFACTS_ACCENTS['chats']}")
            text.append(f" {label}", style="dim")
        return text

    def move_selection(self, _offset: int) -> bool:
        """Keep scaffold navigation inert until chat rows are available."""
        return False

    def entry_targets(self) -> tuple[ArtifactEntryTarget, ...]:
        return ()

    def selected_entry_target(self) -> ArtifactEntryTarget | None:
        return None

    def select_entry_target(self, _target: ArtifactEntryTarget) -> bool:
        return False

    def apply_entry_jump_hints(
        self,
        _hints: Mapping[ArtifactEntryTarget, str],
    ) -> None:
        return None

    def clear_entry_jump_hints(self) -> None:
        return None


__all__ = ["ArtifactsChatsPane"]
