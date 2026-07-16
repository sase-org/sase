"""Top-level Artifacts view with sub-tab switching and lifecycle routing."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, cast

from textual import on
from textual.app import ComposeResult
from textual.containers import Vertical
from textual.widgets import ContentSwitcher

from ...keymaps import KeymapRegistry
from ...tab_order import ARTIFACTS_TAB
from ..panel_tab_strip import PanelTab, PanelTabStrip
from .commits import CommitsPane
from .panes import (
    ArtifactPlaceholderPane,
    ArtifactsPaneLifecycle,
    ArtifactsPrsPane,
)
from .plans_pane import ArtifactsPlansPane
from .types import (
    ARTIFACTS_ACCENTS,
    ARTIFACTS_PANE_IDS,
    ARTIFACTS_SUBTAB_ORDER,
    DEFAULT_ARTIFACTS_SUBTAB,
    ArtifactsSubTab,
)

if TYPE_CHECKING:
    from ...app import AceApp

_ARTIFACT_TABS: tuple[PanelTab, ...] = tuple(
    PanelTab(tab, tab.title(), ARTIFACTS_ACCENTS[tab]) for tab in ARTIFACTS_SUBTAB_ORDER
)


class ArtifactsView(Vertical):
    """Host the PR surface and lazy artifact sibling panes."""

    def __init__(self, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self._current_subtab: ArtifactsSubTab = DEFAULT_ARTIFACTS_SUBTAB

    def compose(self) -> ComposeResult:
        yield PanelTabStrip(
            _ARTIFACT_TABS,
            self._current_subtab,
            id="artifacts-subtabs",
        )
        with ContentSwitcher(
            initial=ARTIFACTS_PANE_IDS[self._current_subtab],
            id="artifacts-content-switcher",
        ):
            yield ArtifactsPrsPane(id=ARTIFACTS_PANE_IDS["prs"])
            yield CommitsPane(id=ARTIFACTS_PANE_IDS["commits"])
            for subtab in ARTIFACTS_SUBTAB_ORDER[2:-1]:
                yield ArtifactPlaceholderPane(
                    subtab,
                    id=ARTIFACTS_PANE_IDS[subtab],
                )
            yield ArtifactsPlansPane(id=ARTIFACTS_PANE_IDS["plans"])

    def on_mount(self) -> None:
        # The PR pane is the only eager lifecycle. Its existing widgets are
        # loaded by the app's established startup path.
        prs = self._pane("prs")
        prs.activate()
        if getattr(self.app, "current_tab", None) != ARTIFACTS_TAB:
            prs.deactivate()

    @property
    def current_subtab(self) -> ArtifactsSubTab:
        return self._current_subtab

    def _pane(self, subtab: ArtifactsSubTab) -> ArtifactsPaneLifecycle:
        pane = self.query_one(f"#{ARTIFACTS_PANE_IDS[subtab]}")
        return cast(ArtifactsPaneLifecycle, pane)

    def switch_to(self, subtab: ArtifactsSubTab) -> None:
        """Switch visible content and route active-pane lifecycle hooks."""
        old_subtab = self._current_subtab
        if old_subtab == subtab:
            return
        artifacts_visible = getattr(self.app, "current_tab", None) == ARTIFACTS_TAB
        if artifacts_visible:
            self._pane(old_subtab).deactivate()
        self._current_subtab = subtab
        self.query_one(
            "#artifacts-content-switcher", ContentSwitcher
        ).current = ARTIFACTS_PANE_IDS[subtab]
        self.query_one("#artifacts-subtabs", PanelTabStrip).set_active_tab(subtab)
        if artifacts_visible:
            self._pane(subtab).activate()

    def activate_current(self) -> None:
        """Resume the visible pane after entering the top-level tab."""
        self._pane(self._current_subtab).activate()

    def deactivate_current(self) -> None:
        """Pause the visible pane before leaving the top-level tab."""
        self._pane(self._current_subtab).deactivate()

    def request_active_refresh(self) -> None:
        """Route an auto/manual refresh only to the currently active pane."""
        self._pane(self._current_subtab).request_refresh()

    def set_keymap_registry(self, registry: KeymapRegistry) -> None:
        """Forward configured key display to project-backed panes."""
        for pane in self.query(ArtifactPlaceholderPane):
            pane.set_keymap_registry(registry)
        for plans_pane in self.query(ArtifactsPlansPane):
            plans_pane.set_keymap_registry(registry)

    def set_project_scope(
        self,
        project: str | None,
        *,
        display_name: str | None = None,
        project_file: str | None = None,
    ) -> None:
        """Apply the shared scope to every project-backed pane."""
        self.query_one(CommitsPane).set_project_scope(
            project,
            display_name=display_name,
            project_file=project_file,
        )
        for pane in self.query(ArtifactPlaceholderPane):
            pane.set_project_scope(project, display_name=display_name)
        for plans_pane in self.query(ArtifactsPlansPane):
            plans_pane.set_project_scope(project, display_name=display_name)

    @on(PanelTabStrip.TabClicked)
    def _on_subtab_clicked(self, event: PanelTabStrip.TabClicked) -> None:
        if event.tab_id not in ARTIFACTS_SUBTAB_ORDER:
            return
        event.stop()
        cast("AceApp", self.app).current_artifacts_subtab = cast(
            ArtifactsSubTab, event.tab_id
        )


__all__ = ["ArtifactsView"]
