"""Typed Config-hub session bookmarks and one-shot direct-entry seeds."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal

from .catalog_pane_contract import CatalogPaneSession

ConfigSubTab = Literal[
    "flags", "glossary", "launch", "memory", "misc", "snippets", "xprompts"
]
CONFIG_SUBTAB_ORDER: tuple[ConfigSubTab, ...] = (
    "misc",
    "flags",
    "glossary",
    "launch",
    "memory",
    "snippets",
    "xprompts",
)
CONFIG_SUBTAB_ORDER_WITHOUT_FLAGS: tuple[ConfigSubTab, ...] = tuple(
    subtab for subtab in CONFIG_SUBTAB_ORDER if subtab != "flags"
)


def config_subtab_order() -> tuple[ConfigSubTab, ...]:
    """Return the active Config catalog order for this process.

    Reads only the already-pinned feature-flag snapshot. Never called at
    module import time.
    """
    if _admin_center_flags_enabled():
        return CONFIG_SUBTAB_ORDER
    return CONFIG_SUBTAB_ORDER_WITHOUT_FLAGS


def _admin_center_flags_enabled() -> bool:
    from sase.feature_flags import FeatureFlag, current_flags

    return current_flags().enabled(FeatureFlag.admin_center_flags)


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
    flags: CatalogPaneSession = field(default_factory=CatalogPaneSession)
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
    "CONFIG_SUBTAB_ORDER_WITHOUT_FLAGS",
    "config_subtab_order",
    "validated_config_subtab",
]
