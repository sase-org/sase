"""Tab identities, metadata, and lazy pane factories for the Admin Center."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Literal, cast

from textual.widget import Widget

from ..widgets.panel_tab_strip import PanelTab

if TYPE_CHECKING:
    from .config_center_modal import ConfigCenterModal


CenterTab = Literal[
    "config", "logs", "procs", "projects", "statistics", "updates", "xprompts"
]
PaneFactory = Callable[["ConfigCenterModal"], Widget]


@dataclass(frozen=True)
class CenterTabSpec:
    """Immutable navigation and construction metadata for one working tab."""

    id: CenterTab
    number: int
    label: str
    accent: str
    description: str
    pane_identity: str
    factory: PaneFactory


def _config_pane_factory(modal: ConfigCenterModal) -> Widget:
    from .config_pane import ConfigPane

    return ConfigPane(
        project=modal._project,
        bookmark=modal._session_state.config,
        id="config",
    )


def _logs_pane_factory(_modal: ConfigCenterModal) -> Widget:
    from .logs_pane import LogsPane

    return LogsPane(bookmark=_modal._session_state.logs, id="logs")


def _projects_pane_factory(_modal: ConfigCenterModal) -> Widget:
    from .projects_pane import ProjectsPane

    return ProjectsPane(session_state=_modal._session_state.projects, id="projects")


def _statistics_pane_factory(modal: ConfigCenterModal) -> Widget:
    from .statistics_pane import StatisticsPane

    registry = getattr(modal.app, "_keymap_registry", None)
    keymaps = getattr(registry, "statistics", None)
    return StatisticsPane(id="statistics", keymaps=keymaps)


def _procs_pane_factory(_modal: ConfigCenterModal) -> Widget:
    from .procs_pane import ProcsPane

    return ProcsPane(session_state=_modal._session_state.procs, id="procs")


def _updates_pane_factory(modal: ConfigCenterModal) -> Widget:
    from .plugins_browser_pane import PluginsBrowserPane

    return PluginsBrowserPane(
        id="updates",
        auto_update_on_load=modal._auto_update,
        comprehensive_provider_names=modal._comprehensive_provider_names,
        session_state=modal._session_state.updates,
    )


def _xprompts_pane_factory(modal: ConfigCenterModal) -> Widget:
    from .xprompt_browser_pane import XPromptBrowserPane

    return XPromptBrowserPane(
        modal._project,
        bookmark=modal._session_state.xprompts,
        id="xprompts",
    )


_TAB_SPECS: tuple[CenterTabSpec, ...] = (
    CenterTabSpec(
        "config",
        1,
        "Config",
        "#00D7AF",
        "Review and edit layered SASE settings with provenance and live previews.",
        "ConfigPane",
        _config_pane_factory,
    ),
    CenterTabSpec(
        "logs",
        2,
        "Logs",
        "#FFD700",
        "Inspect TUI activity, launch failures, and notification history.",
        "LogsPane",
        _logs_pane_factory,
    ),
    CenterTabSpec(
        "projects",
        3,
        "Projects",
        "#FFAF5F",
        "Manage projects and inspect their repositories and workspaces.",
        "ProjectsPane",
        _projects_pane_factory,
    ),
    CenterTabSpec(
        "statistics",
        4,
        "Statistics",
        "#FF87D7",
        "Explore runners, projects, activity, and trends over time.",
        "StatisticsPane",
        _statistics_pane_factory,
    ),
    CenterTabSpec(
        "procs",
        5,
        "Tasks",
        "#5FD75F",
        "Follow background work, inspect live output, and manage running jobs.",
        "ProcsPane",
        _procs_pane_factory,
    ),
    CenterTabSpec(
        "updates",
        6,
        "Updates",
        "#AF87FF",
        "Update SASE, plugins, and supported agent CLIs from one place.",
        "PluginsBrowserPane",
        _updates_pane_factory,
    ),
    CenterTabSpec(
        "xprompts",
        7,
        "XPrompts",
        "#87D7FF",
        "Find, preview, and load reusable prompts and workflows.",
        "XPromptBrowserPane",
        _xprompts_pane_factory,
    ),
)
_TAB_BY_ID: dict[CenterTab, CenterTabSpec] = {spec.id: spec for spec in _TAB_SPECS}
_TAB_BY_NUMBER: dict[int, CenterTabSpec] = {spec.number: spec for spec in _TAB_SPECS}
_TAB_ORDER: tuple[CenterTab, ...] = tuple(spec.id for spec in _TAB_SPECS)
_TAB_LABELS: list[tuple[CenterTab, str]] = [
    (spec.id, spec.label) for spec in _TAB_SPECS
]
_TAB_COLORS: dict[CenterTab, str] = {spec.id: spec.accent for spec in _TAB_SPECS}
_TAB_DESCRIPTIONS: dict[CenterTab, str] = {
    spec.id: spec.description for spec in _TAB_SPECS
}
_PANEL_TABS: tuple[PanelTab, ...] = tuple(
    PanelTab(spec.id, spec.label, spec.accent) for spec in _TAB_SPECS
)


def center_tab_accent(tab: str) -> str | None:
    """Return the accent color for an Admin Center tab, if it exists."""
    spec = _TAB_BY_ID.get(cast(Any, tab))
    return spec.accent if spec is not None else None


def validated_center_tab(value: object) -> CenterTab | None:
    """Return a catalog-backed Admin Center tab identity, if valid."""
    if isinstance(value, str) and value in _TAB_BY_ID:
        return cast(CenterTab, value)
    return None
