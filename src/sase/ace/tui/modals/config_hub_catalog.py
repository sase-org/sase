"""Immutable Config sub-tab catalog and lazy child factories."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import TYPE_CHECKING

from textual.widget import Widget

from ..widgets.panel_tab_strip import PanelTab
from .config_hub_session import ConfigHubEntry, ConfigSubTab, config_subtab_order

if TYPE_CHECKING:
    from .config_hub_pane import ConfigHubPane

ConfigPaneFactory = Callable[["ConfigHubPane"], Widget]
_CONFIG_ACCENT = "#00D7AF"


@dataclass(frozen=True)
class _ConfigSubTabSpec:
    """Navigation and construction metadata for one Config catalog child."""

    id: ConfigSubTab
    label: str
    compact_label: str
    micro_label: str
    factory: ConfigPaneFactory


def _xprompts_factory(hub: ConfigHubPane) -> Widget:
    from .xprompt_browser_pane import XPromptBrowserPane

    pane = XPromptBrowserPane(
        hub._project,
        bookmark=hub._session_state.xprompts,
        id="xprompts",
    )
    pane.add_class("-embedded")
    return pane


def _snippets_factory(hub: ConfigHubPane) -> Widget:
    from .snippets_panel import SnippetsPane, SnippetsPaneHost

    entry = hub._entry
    host: SnippetsPaneHost = hub
    pane = SnippetsPane(
        launch_workspace=_entry_workspace(entry),
        initial_trigger=_entry_trigger(entry),
        session_state=hub._session_state.config_hub.snippets_session(),
        host=host,
        id="snippets",
    )
    pane.add_class("-embedded")
    return pane


def _glossary_factory(hub: ConfigHubPane) -> Widget:
    from .glossary_pane import GlossaryPane

    entry = hub._entry
    pane = GlossaryPane(
        launch_workspace=_entry_workspace(entry),
        initial_term=_entry_term(entry),
        host=hub,
        session=hub._session_state.config_hub.glossary,
        id="glossary",
    )
    pane.add_class("-embedded")
    return pane


def _memory_factory(hub: ConfigHubPane) -> Widget:
    from .memory_pane import MemoryPane

    entry = hub._entry
    pane = MemoryPane(
        host=hub,
        launch_workspace=_entry_workspace(entry),
        initial_note=_entry_note(entry),
        session=hub._session_state.config_hub.memory_session(),
        activate_on_mount=True,
        id="memory",
    )
    pane.add_class("-embedded")
    return pane


def _launch_factory(hub: ConfigHubPane) -> Widget:
    from .models_panel import LaunchPane

    pane = LaunchPane(
        host=hub,
        session_state=hub._session_state.config_hub.launch_session(),
        display_mode="embedded",
        activate_on_mount=hub._host_visible,
        id="launch",
    )
    pane.add_class("-embedded")
    return pane


def _misc_factory(hub: ConfigHubPane) -> Widget:
    from .config_pane import ConfigPane

    pane = ConfigPane(
        project=hub._project,
        bookmark=hub._session_state.config,
        id="misc",
    )
    pane.add_class("-embedded")
    return pane


def _entry_workspace(entry: ConfigHubEntry | None) -> str | None:
    return None if entry is None else entry.launch_workspace


def _entry_term(entry: ConfigHubEntry | None) -> str | None:
    if entry is None or entry.subtab != "glossary":
        return None
    return entry.term


def _entry_note(entry: ConfigHubEntry | None) -> str | None:
    if entry is None or entry.subtab != "memory":
        return None
    return entry.note


def _entry_trigger(entry: ConfigHubEntry | None) -> str | None:
    if entry is None or entry.subtab != "snippets":
        return None
    return entry.trigger


CONFIG_SUBTAB_SPECS: tuple[_ConfigSubTabSpec, ...] = (
    _ConfigSubTabSpec("glossary", "Glossary", "Glossary", "Gloss", _glossary_factory),
    _ConfigSubTabSpec("launch", "Launch", "Launch", "Run", _launch_factory),
    _ConfigSubTabSpec("memory", "Memory", "Memory", "Mem", _memory_factory),
    _ConfigSubTabSpec("misc", "Misc", "Misc", "Misc", _misc_factory),
    _ConfigSubTabSpec("snippets", "Snippets", "Snippets", "Snip", _snippets_factory),
    _ConfigSubTabSpec("xprompts", "XPrompts", "XPrompts", "XP", _xprompts_factory),
)
CONFIG_SUBTAB_BY_ID: dict[ConfigSubTab, _ConfigSubTabSpec] = {
    spec.id: spec for spec in CONFIG_SUBTAB_SPECS
}
CONFIG_SUBTAB_ORDER: tuple[ConfigSubTab, ...] = tuple(
    spec.id for spec in CONFIG_SUBTAB_SPECS
)
RELATION_SUBTABS: frozenset[ConfigSubTab] = frozenset(
    ("snippets", "glossary", "memory")
)


def config_subtab_specs() -> tuple[_ConfigSubTabSpec, ...]:
    """Return the active Config child specs in navigation order."""
    by_id = CONFIG_SUBTAB_BY_ID
    return tuple(by_id[subtab] for subtab in config_subtab_order())


def config_subtab_by_id() -> dict[ConfigSubTab, _ConfigSubTabSpec]:
    """Return the active Config child spec map."""
    return {spec.id: spec for spec in config_subtab_specs()}


def config_panel_tabs() -> tuple[PanelTab, ...]:
    """Return PanelTab metadata for the active Config catalog."""
    return tuple(
        PanelTab(
            spec.id,
            spec.label,
            _CONFIG_ACCENT,
            compact_label=spec.compact_label,
            micro_label=spec.micro_label,
            shortcut=f"{index:02d}",
        )
        for index, spec in enumerate(config_subtab_specs(), start=1)
    )


CONFIG_PANEL_TABS: tuple[PanelTab, ...] = tuple(
    PanelTab(
        spec.id,
        spec.label,
        _CONFIG_ACCENT,
        compact_label=spec.compact_label,
        micro_label=spec.micro_label,
        shortcut=f"{index:02d}",
    )
    for index, spec in enumerate(CONFIG_SUBTAB_SPECS, start=1)
)

__all__ = [
    "CONFIG_PANEL_TABS",
    "CONFIG_SUBTAB_BY_ID",
    "CONFIG_SUBTAB_ORDER",
    "CONFIG_SUBTAB_SPECS",
    "ConfigPaneFactory",
    "RELATION_SUBTABS",
    "config_panel_tabs",
    "config_subtab_by_id",
    "config_subtab_specs",
]
