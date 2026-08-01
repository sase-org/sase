"""Nested Files view that hosts Plans, Chats, and Other artifact panes."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, cast

from textual import on
from textual.app import ComposeResult
from textual.containers import Vertical, VerticalScroll
from textual.widgets import ContentSwitcher

from ...keymaps import KeymapRegistry
from ..panel_tab_strip import PanelTab, PanelTabStrip
from .chats_pane import ArtifactsChatsPane
from .entry_navigation import ArtifactEntryNavigator
from .files_pane import ArtifactsFilesPane
from .lifecycle import ArtifactsPaneLifecycle
from .plans_pane import ArtifactsPlansPane
from .types import (
    ARTIFACTS_ACCENTS,
    DEFAULT_FILES_SUBTAB,
    FILES_PANE_IDS,
    FILES_SUBTAB_ORDER,
    FilesSubTab,
)

if TYPE_CHECKING:
    from sase.project_display_names import ProjectRefDisplaySnapshot

    from ...app import AceApp


_FILES_LABELS: dict[FilesSubTab, str] = {
    "plans": "Plans",
    "chats": "Chats",
    "other": "Other",
}
_FILES_TABS: tuple[PanelTab, ...] = tuple(
    PanelTab(tab, _FILES_LABELS[tab], ARTIFACTS_ACCENTS[tab])
    for tab in FILES_SUBTAB_ORDER
)
_DETAIL_SCROLL_IDS: dict[FilesSubTab, str] = {
    "plans": "plans-detail-scroll",
    "chats": "chats-detail-scroll",
    "other": "files-detail-scroll",
}


class ArtifactsFilesView(ArtifactsPaneLifecycle, Vertical):
    """Keep Files child panes mounted while routing one active lifecycle."""

    def __init__(self, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self._current_subtab: FilesSubTab = DEFAULT_FILES_SUBTAB
        self._init_artifacts_lifecycle()

    def compose(self) -> ComposeResult:
        yield PanelTabStrip(
            _FILES_TABS,
            self._current_subtab,
            show_numbers=False,
            uppercase_active=True,
            id="artifacts-files-subtabs",
        )
        with ContentSwitcher(
            initial=FILES_PANE_IDS[self._current_subtab],
            id="artifacts-files-content-switcher",
        ):
            yield ArtifactsPlansPane(id=FILES_PANE_IDS["plans"])
            yield ArtifactsChatsPane(id=FILES_PANE_IDS["chats"])
            yield ArtifactsFilesPane(id=FILES_PANE_IDS["other"])

    @property
    def current_subtab(self) -> FilesSubTab:
        return self._current_subtab

    def _pane(self, subtab: FilesSubTab) -> ArtifactsPaneLifecycle:
        pane = self.query_one(f"#{FILES_PANE_IDS[subtab]}")
        return cast(ArtifactsPaneLifecycle, pane)

    def switch_to(self, subtab: FilesSubTab) -> None:
        """Switch child content without resetting the remembered child."""

        old_subtab = self._current_subtab
        if old_subtab == subtab:
            return
        if self.artifacts_active:
            self._pane(old_subtab).deactivate()
        self._current_subtab = subtab
        self.query_one(
            "#artifacts-files-content-switcher", ContentSwitcher
        ).current = FILES_PANE_IDS[subtab]
        self.query_one("#artifacts-files-subtabs", PanelTabStrip).set_active_tab(subtab)
        if self.artifacts_active:
            self._pane(subtab).activate()

    def activate_current(self) -> None:
        self._pane(self._current_subtab).activate()

    def deactivate_current(self) -> None:
        self._pane(self._current_subtab).deactivate()

    def request_active_refresh(self) -> None:
        self._pane(self._current_subtab).request_refresh()

    def on_activate(self) -> None:
        self.activate_current()

    def on_deactivate(self) -> None:
        self.deactivate_current()

    def on_refresh(self) -> None:
        self.request_active_refresh()

    def entry_navigator(self, subtab: FilesSubTab) -> ArtifactEntryNavigator:
        return cast(ArtifactEntryNavigator, self._pane(subtab))

    def detail_scroll(self, subtab: FilesSubTab) -> VerticalScroll:
        return self.query_one(f"#{_DETAIL_SCROLL_IDS[subtab]}", VerticalScroll)

    def set_keymap_registry(self, registry: KeymapRegistry) -> None:
        for pane in (
            self.query_one(ArtifactsPlansPane),
            self.query_one(ArtifactsChatsPane),
            self.query_one(ArtifactsFilesPane),
        ):
            pane.set_keymap_registry(registry)

    def set_project_scope(
        self,
        project: str | None,
        *,
        display_name: str | None = None,
    ) -> None:
        for pane in (
            self.query_one(ArtifactsPlansPane),
            self.query_one(ArtifactsChatsPane),
            self.query_one(ArtifactsFilesPane),
        ):
            pane.set_project_scope(project, display_name=display_name)

    def set_project_ref_display(
        self,
        project_ref_display: ProjectRefDisplaySnapshot,
    ) -> None:
        self.query_one(ArtifactsFilesPane).set_project_ref_display(project_ref_display)

    @on(PanelTabStrip.TabClicked)
    def _on_subtab_clicked(self, event: PanelTabStrip.TabClicked) -> None:
        if event.tab_id not in FILES_SUBTAB_ORDER:
            return
        event.stop()
        cast("AceApp", self.app).current_files_subtab = cast(FilesSubTab, event.tab_id)


__all__ = ["ArtifactsFilesView"]
