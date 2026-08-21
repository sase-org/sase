"""Tab identities, metadata, and lazy pane factories for the Admin Center."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Literal, cast

from textual.widget import Widget

from ..widgets.panel_tab_strip import PanelTab

if TYPE_CHECKING:
    from .config_center_modal import ConfigCenterModal


CenterTab = Literal["config", "logs", "procs", "projects", "statistics", "updates"]
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
    from .config_hub_pane import ConfigHubPane

    registry = getattr(modal.app, "_keymap_registry", None)
    keymaps = getattr(registry, "config", None)
    return ConfigHubPane(
        project=modal._project,
        session_state=modal._session_state,
        entry=getattr(modal, "_config_entry", None),
        keymaps=keymaps,
        id="config",
    )


def _logs_pane_factory(_modal: ConfigCenterModal) -> Widget:
    from .logs_pane import LogsPane

    return LogsPane(
        bookmark=_modal._session_state.logs,
        error_target=_modal._log_error_target,
        id="logs",
    )


def _projects_pane_factory(_modal: ConfigCenterModal) -> Widget:
    from .projects_pane import ProjectsPane

    registry = getattr(_modal.app, "_keymap_registry", None)
    keymaps = getattr(registry, "projects", None)
    return ProjectsPane(
        session_state=_modal._session_state.projects,
        keymaps=keymaps,
        id="projects",
    )


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
        session_state=modal._session_state.updates,
    )


_TAB_SPECS: tuple[CenterTabSpec, ...] = (
    CenterTabSpec(
        "config",
        1,
        "Config",
        "#00D7AF",
        "Browse glossary, launch, memory, snippets, XPrompts, and settings.",
        "ConfigHubPane",
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
        "procs",
        3,
        "Procs",
        "#5FD75F",
        "Follow procs, inspect live output, and manage running jobs.",
        "ProcsPane",
        _procs_pane_factory,
    ),
    CenterTabSpec(
        "projects",
        4,
        "Projects",
        "#FFAF5F",
        "Manage projects and inspect their repositories and workspaces.",
        "ProjectsPane",
        _projects_pane_factory,
    ),
    CenterTabSpec(
        "statistics",
        5,
        "Statistics",
        "#FF87D7",
        "Explore runners, projects, activity, and trends over time.",
        "StatisticsPane",
        _statistics_pane_factory,
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
    """Return a catalog-backed Admin Center tab identity, if valid.

    A persisted top-level ``xprompts`` identity from the pre-cutover Admin
    Center maps to ``config`` so old resume state still reaches XPrompts
    through the hub's default child.
    """
    if not isinstance(value, str):
        return None
    migrated = "config" if value == "xprompts" else value
    if migrated in _TAB_BY_ID:
        return cast(CenterTab, migrated)
    return None
