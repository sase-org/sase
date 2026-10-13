"""Shared Projects-pane constants, filter input, and current-project snapshot."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from textual import events

from sase.ace.tui.keymaps import split_key_alternatives
from sase.current_project import CurrentProject

from ..widgets.panel_tab_strip import PanelTab
from .base import FilterInput
from .config_center_session import ProjectsSubTab

if TYPE_CHECKING:
    from .projects_pane import ProjectsPane

SUBTAB_ORDER: tuple[ProjectsSubTab, ...] = (
    "projects",
    "repos",
    "workspaces",
)
SUBTAB_WIDGET_IDS: dict[ProjectsSubTab, str] = {
    "projects": "projects-subtab-projects",
    "repos": "projects-subtab-repos",
    "workspaces": "projects-subtab-workspaces",
}
SUBTABS: tuple[PanelTab, ...] = tuple(
    PanelTab(tab, tab.title(), "#FFAF5F") for tab in SUBTAB_ORDER
)


@dataclass(frozen=True, slots=True)
class CurrentProjectSnapshot:
    """Resolved current project plus the accent computed off-thread."""

    project: CurrentProject | None
    accent: str


class ProjectsFilterInput(FilterInput):
    """Filter input that forwards printable sub-tab cycle keys."""

    def on_key(self, event: events.Key) -> None:
        pane = self._pane()
        if pane is None:
            return
        if event.key in split_key_alternatives(pane._keymaps.cycle_subtab_reverse):
            event.stop()
            event.prevent_default()
            pane.action_cycle_subtab_reverse()
        elif event.key in split_key_alternatives(pane._keymaps.cycle_subtab):
            event.stop()
            event.prevent_default()
            pane.action_cycle_subtab()

    def _pane(self) -> ProjectsPane | None:
        from .projects_pane import ProjectsPane

        node: object | None = self.parent
        while node is not None:
            if isinstance(node, ProjectsPane):
                return node
            node = getattr(node, "parent", None)
        return None
