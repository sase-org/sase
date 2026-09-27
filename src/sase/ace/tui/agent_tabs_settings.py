"""Typed reader for the ``ace.agent_tabs`` configuration block."""

from __future__ import annotations

from dataclasses import dataclass, field
from functools import lru_cache
from typing import Any, Literal
from collections.abc import Mapping

from sase.config import load_merged_config
from sase.config.core import current_config_token
from sase.dispatch.config import load_dispatch_config

MachineTabsMode = Literal["auto", "on", "off"]

DEFAULT_MACHINE_TABS: MachineTabsMode = "auto"
DEFAULT_LAUNCH_FROM_VIEW = True


@dataclass(frozen=True, slots=True)
class AgentTabStyle:
    """Presentation settings for one named agent tab.

    Consumed by later agent-tabs phases (styling keys and ``order``); the
    tab-foundation phase only parses and stores them.
    """

    color: str = ""
    icon: str = ""
    order: int | None = None
    description: str = ""


@dataclass(frozen=True, slots=True)
class AgentTabsSettings:
    """Cached agent-tabs behavior settings used by ACE."""

    machine_tabs: MachineTabsMode = DEFAULT_MACHINE_TABS
    launch_from_view: bool = DEFAULT_LAUNCH_FROM_VIEW
    tabs: Mapping[str, AgentTabStyle] = field(default_factory=dict)


DEFAULT_AGENT_TABS_SETTINGS = AgentTabsSettings()


def _coerce_machine_tabs(value: object) -> MachineTabsMode:
    if value in ("auto", "on", "off"):
        return value  # type: ignore[return-value]
    return DEFAULT_MACHINE_TABS


def _coerce_order(value: object) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    return None


def _coerce_text(value: object) -> str:
    if not isinstance(value, str):
        return ""
    return value.strip()


def _parse_tab_style(raw: object) -> AgentTabStyle | None:
    if not isinstance(raw, dict):
        return None
    return AgentTabStyle(
        color=_coerce_text(raw.get("color")),
        icon=_coerce_text(raw.get("icon")),
        order=_coerce_order(raw.get("order")),
        description=_coerce_text(raw.get("description")),
    )


def parse_agent_tabs_settings(ace_cfg: object) -> AgentTabsSettings:
    """Parse ``ace.agent_tabs`` with safe package fallbacks.

    Non-mapping ``ace`` blocks, missing or non-mapping ``agent_tabs``
    objects, unknown ``machine_tabs`` modes, and non-boolean
    ``launch_from_view`` values all fall back to the defaults. Tab names are
    canonicalized through ``canonicalize_agent_tab``; invalid names (and the
    default tab, which takes no name-keyed styling) are dropped.
    """
    if not isinstance(ace_cfg, dict):
        return DEFAULT_AGENT_TABS_SETTINGS
    raw = ace_cfg.get("agent_tabs")
    if not isinstance(raw, dict):
        return DEFAULT_AGENT_TABS_SETTINGS
    machine_tabs = _coerce_machine_tabs(raw.get("machine_tabs"))
    launch_from_view = raw.get("launch_from_view", DEFAULT_LAUNCH_FROM_VIEW)
    if not isinstance(launch_from_view, bool):
        launch_from_view = DEFAULT_LAUNCH_FROM_VIEW
    tabs: dict[str, AgentTabStyle] = {}
    raw_tabs = raw.get("tabs", {})
    if isinstance(raw_tabs, dict):
        from sase.core.agent_tab import canonicalize_agent_tab

        for name, style_raw in raw_tabs.items():
            if not isinstance(name, str):
                continue
            try:
                canonical = canonicalize_agent_tab(name)
            except Exception:  # noqa: BLE001 - invalid names are dropped.
                continue
            if canonical is None:
                continue
            style = _parse_tab_style(style_raw)
            if style is None:
                continue
            tabs[canonical] = style
    return AgentTabsSettings(
        machine_tabs=machine_tabs,
        launch_from_view=launch_from_view,
        tabs=tabs,
    )


def agent_tabs_settings_for(widget: object) -> AgentTabsSettings:
    """Return the app's agent-tabs settings, failing open to the default."""
    try:
        app = getattr(widget, "app", None)
        settings = getattr(app, "_agent_tabs_settings", None)
        if isinstance(settings, AgentTabsSettings):
            return settings
    except Exception:
        pass
    return DEFAULT_AGENT_TABS_SETTINGS


@dataclass(frozen=True, slots=True)
class AgentTabsViewConfig:
    """Token-cached machine-mode and ordering projection for agent tabs.

    Never computed from fleet refresh results: ``machine_mode`` and
    ``machine_order`` come from the dispatch machine records, and
    ``named_order`` comes from ``ace.agent_tabs`` styling.
    """

    machine_mode: bool = False
    machine_order: tuple[tuple[str, str], ...] = ()
    pinned_by_alias: Mapping[str, str] = field(default_factory=dict)
    named_order: Mapping[str, int] = field(default_factory=dict)
    token: tuple[Any, ...] = ()


@lru_cache(maxsize=1)
def _agent_tabs_view_config_for_token(
    _token: tuple[Any, ...],
) -> AgentTabsViewConfig:
    """Resolve the agent-tabs view config once per merged-config token."""
    try:
        config = load_merged_config()
    except Exception:  # noqa: BLE001 - fail open to the default view.
        return AgentTabsViewConfig(token=_token)
    if not isinstance(config, dict):
        return AgentTabsViewConfig(token=_token)
    ace_cfg = config.get("ace", {})
    settings = parse_agent_tabs_settings(ace_cfg if isinstance(ace_cfg, dict) else {})
    try:
        dispatch = load_dispatch_config(config)
    except Exception:  # noqa: BLE001 - fail open to the default view.
        return AgentTabsViewConfig(token=_token)
    machines = dispatch.machines or ()
    if settings.machine_tabs == "on":
        machine_mode = True
    elif settings.machine_tabs == "off":
        machine_mode = False
    else:
        machine_mode = len(machines) > 0
    machine_order: list[tuple[str, str]] = []
    pinned_by_alias: dict[str, str] = {}
    for record in machines:
        pinned = getattr(record, "pinned_installation_id", "")
        alias = getattr(record, "alias", "")
        if isinstance(alias, str) and alias and isinstance(pinned, str) and pinned:
            pinned_by_alias.setdefault(alias, pinned)
        if isinstance(pinned, str) and pinned:
            machine_order.append((pinned, alias if isinstance(alias, str) else ""))
    named_order = {
        name: style.order
        for name, style in settings.tabs.items()
        if style.order is not None
    }
    token = (
        machine_mode,
        tuple(machine_order),
        tuple(sorted(named_order.items())),
    )
    return AgentTabsViewConfig(
        machine_mode=machine_mode,
        machine_order=tuple(machine_order),
        pinned_by_alias=pinned_by_alias,
        named_order=named_order,
        token=token,
    )


def agent_tabs_view_config() -> AgentTabsViewConfig:
    """Return the cached agent-tabs view config for the current config token."""
    return _agent_tabs_view_config_for_token(current_config_token())


__all__ = [
    "DEFAULT_AGENT_TABS_SETTINGS",
    "DEFAULT_LAUNCH_FROM_VIEW",
    "DEFAULT_MACHINE_TABS",
    "AgentTabStyle",
    "AgentTabsSettings",
    "AgentTabsViewConfig",
    "agent_tabs_settings_for",
    "agent_tabs_view_config",
    "parse_agent_tabs_settings",
]
