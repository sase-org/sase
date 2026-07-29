"""Empty lifecycle shell for the Artifacts Files pane."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from rich.text import Text
from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.widgets import OptionList, Static

from ...keymaps import KeymapRegistry, key_display_name, load_keymap_registry
from .entry_navigation import ArtifactEntryTarget
from .lifecycle import ArtifactsPaneLifecycle
from .types import ARTIFACTS_ACCENTS


class ArtifactsFilesPane(ArtifactsPaneLifecycle, Vertical):
    """Mounted Files pane ready for later loading and rendering phases."""

    can_focus = False

    def __init__(self, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self.project_scope: str | None = None
        self._project_display_name: str | None = None
        self._registry = load_keymap_registry({})
        self._entry_marks: set[ArtifactEntryTarget] = set()
        self._init_artifacts_lifecycle()

    def compose(self) -> ComposeResult:
        yield Static("", id="file-filter-bar")
        yield Static(
            self._scope_text(),
            id="files-info",
            classes="artifacts-pane-info",
        )
        with Horizontal(id="files-panels"):
            list_panel = Vertical(id="files-list-panel")
            list_panel.border_title = "Files"
            with list_panel:
                yield Static("No artifact files found.", id="files-empty")
                status = Static("", id="files-status")
                status.display = False
                yield status
                option_list = OptionList(id="files-list")
                option_list.display = False
                yield option_list
            detail_panel = Vertical(id="files-detail-panel")
            detail_panel.border_title = "Details"
            with detail_panel:
                with VerticalScroll(id="files-detail-scroll"):
                    yield Static("", id="files-detail")
        yield Static(self._hints_text(), id="files-hints")

    def set_keymap_registry(self, registry: KeymapRegistry) -> None:
        self._registry = registry
        self._update_static("#files-info", self._scope_text())
        self._update_static("#files-hints", self._hints_text())

    def set_project_scope(
        self,
        project: str | None,
        *,
        display_name: str | None = None,
    ) -> None:
        self.project_scope = project
        self._project_display_name = display_name
        self._update_static("#files-info", self._scope_text())

    def focus_list(self) -> None:
        if self.is_mounted:
            self.query_one("#files-list", OptionList).focus()

    def move_selection(self, _offset: int) -> bool:
        """Leave the empty scaffold unchanged until rows are implemented."""
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
        return

    def clear_entry_jump_hints(self) -> None:
        return

    def apply_entry_marks(self, marks: set[ArtifactEntryTarget]) -> None:
        self._entry_marks = set(marks)

    def _scope_text(self) -> Text:
        accent = ARTIFACTS_ACCENTS["files"]
        label = self._project_display_name or self.project_scope or "All projects"
        text = Text()
        text.append(" Files ", style=f"bold #1a1a1a on {accent}")
        text.append("  Project scope  ", style="dim")
        text.append(f" {label} ", style=f"bold {accent}")
        text.append("  ·  ", style="dim")
        text.append(
            f"{key_display_name(self._registry.app.pick_artifacts_project)} change",
            style="dim",
        )
        return text

    def _hints_text(self) -> Text:
        keymap = self._registry.app
        accent = ARTIFACTS_ACCENTS["files"]
        hints = (
            (keymap.files_view_selected, "view"),
            (keymap.files_filters, "filter"),
            (keymap.files_cycle_kind, "kind"),
            (keymap.files_open_agent, "agent"),
            (keymap.files_open_external, "external"),
            (keymap.files_copy_reference, "copy ref"),
            (keymap.files_copy_path, "copy path"),
            (keymap.files_open_viewer, "viewer"),
            (keymap.files_refresh, "refresh"),
        )
        text = Text(justify="center")
        for index, (key, label) in enumerate(hints):
            if index:
                text.append("   ", style="dim")
            text.append(key_display_name(key), style=f"bold {accent}")
            text.append(f" {label}", style="dim")
        return text

    def _update_static(self, selector: str, content: Text) -> None:
        if self.is_mounted:
            self.query_one(selector, Static).update(content)


__all__ = ["ArtifactsFilesPane"]
