"""Typed Config-hub session bookmarks and one-shot direct-entry seeds."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal

from .catalog_pane_contract import CatalogPaneSession

ConfigSubTab = Literal["glossary", "launch", "memory", "misc", "snippets", "xprompts"]
CONFIG_SUBTAB_ORDER: tuple[ConfigSubTab, ...] = (
    "glossary",
    "launch",
    "memory",
    "misc",
    "snippets",
    "xprompts",
)


def config_subtab_order() -> tuple[ConfigSubTab, ...]:
    """Return the active Config catalog order for this process."""
    return CONFIG_SUBTAB_ORDER


def validated_config_subtab(value: object) -> ConfigSubTab | None:
    """Return a catalog-backed Config sub-tab identity, if valid."""
    if isinstance(value, str) and value in config_subtab_order():
        return value  # type: ignore[return-value]
    return None


@dataclass(frozen=True, slots=True)
class ConfigHubEntry:
    """One-shot Config target shared by prompt shortcuts and the hub.

    Carries the requested sub-tab plus only the launch workspace and the
    seed that sub-tab understands. Explicit seeds win once on first load
    without wiping bookmarks for other scopes.
    """

    subtab: ConfigSubTab
    launch_workspace: str | None = None
    term: str | None = None
    note: str | None = None
    trigger: str | None = None


@dataclass
class ConfigHubSessionState:
    """Session-only Config catalog cursor: active child plus per-tool bookmarks.

    Glossary uses the shared catalog bookmark. Memory and Snippets session
    objects are created on first Config-hub mount so constructing an
    :class:`AdminCenterSessionState` does not import those pane modules.
    """

    active_subtab: ConfigSubTab = "xprompts"
    glossary: CatalogPaneSession = field(default_factory=CatalogPaneSession)
    memory: Any = None
    launch: Any = None
    snippets: Any = None

    def memory_session(self) -> Any:
        """Return the Memory bookmark, creating it on first use."""
        if self.memory is None:
            from .memory_pane import MemoryPaneSession

            self.memory = MemoryPaneSession()
        return self.memory

    def launch_session(self) -> Any:
        """Return the Launch bookmark, creating it on first use."""
        if self.launch is None:
            from .models_panel_types import LaunchPaneSessionState

            self.launch = LaunchPaneSessionState()
        return self.launch

    def snippets_session(self) -> Any:
        """Return the Snippets bookmark, creating it on first use."""
        if self.snippets is None:
            from .snippets_panel import SnippetsPaneSessionState

            self.snippets = SnippetsPaneSessionState()
        return self.snippets


__all__ = [
    "ConfigHubEntry",
    "ConfigHubSessionState",
    "ConfigSubTab",
    "CONFIG_SUBTAB_ORDER",
    "config_subtab_order",
    "validated_config_subtab",
]
