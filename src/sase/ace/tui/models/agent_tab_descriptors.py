"""Query-aware agent tab descriptor projection (pure, no I/O).

Tab *existence* comes from the ordered catalog built over the
tab-independent roster (``_agents_with_children``); counts and attention
come from the committed, tab-independent query result
(``_agents_query_result``), so typing a query changes counts but never
which tabs exist. Rendering and tab switches stay free of disk, network,
and roster projection work: every input here is already in memory.
"""

from __future__ import annotations

from collections.abc import Collection, Mapping
from dataclasses import dataclass, field
from typing import Any

from sase.core.agent_tab import AgentTabKey

from sase.ace.tui.widgets.agent_tab_strip import (
    MACHINE_GLYPH,
    AgentTabDescriptor,
    agent_tab_accent_for_name,
)

_MACHINE_GLYPH_PREFIX = f"{MACHINE_GLYPH} "


def _split_machine_label(catalog_label: str) -> tuple[str, str]:
    """Split a catalog label into ``(glyph, label)``.

    Machine tabs (and the default tab in machine mode) arrive from the
    catalog as ``"⌨ <alias>"``; named tabs and the non-machine default
    carry no glyph.
    """
    if catalog_label.startswith(_MACHINE_GLYPH_PREFIX):
        return MACHINE_GLYPH, catalog_label[len(_MACHINE_GLYPH_PREFIX) :]
    if catalog_label == MACHINE_GLYPH:
        return MACHINE_GLYPH, ""
    return "", catalog_label


def project_agent_tab_descriptors(
    entries: tuple[Any, ...],
    query_rows: Collection[Any],
    key_for: Any,
    *,
    active_key: AgentTabKey | None = None,
    unread_ids: Collection[tuple[Any, ...]] = (),
    incomplete: bool = False,
    health_by_key: Mapping[AgentTabKey, str] | None = None,
    arrivals: Collection[AgentTabKey] | None = None,
    config_colors: Mapping[str, str] | None = None,
    config_icons: Mapping[str, str] | None = None,
    config_descriptions: Mapping[str, str] | None = None,
    enabled_projects: tuple[str, ...] = (),
    machine_mode: bool = False,
    jump_hints: Mapping[AgentTabKey, str] | None = None,
    extra_tooltips: Mapping[AgentTabKey, str] | None = None,
) -> tuple[AgentTabDescriptor, ...]:
    """Project one descriptor per catalog entry (pure, no I/O).

    *entries* are catalog entries with ``key``/``label`` (existence);
    *query_rows* is the committed tab-independent query result, grouped by
    *key_for* into per-tab top-level counts and ``S``/``F``/``U``
    attention via the same status projection the tribe panel titles use.
    The latched emptied tab is just another entry with no query rows, so
    it renders with count 0 and its pill intact.
    """
    from sase.ace.tui.models._agent_clan import sase_agent_status_counts
    from sase.ace.tui.models._agent_tree import agent_is_tree_child

    health = health_by_key or {}
    arrived = set(arrivals or ())
    colors = config_colors or {}
    icons = config_icons or {}
    descriptions = config_descriptions or {}
    hints = jump_hints or {}
    tooltip_extras: Mapping[AgentTabKey, str] = extra_tooltips or {}

    rows_by_key: dict[AgentTabKey, list[Any]] = {}
    for row in query_rows:
        try:
            key = key_for(row)
        except Exception:  # noqa: BLE001 - unknown rows stay uncounted.
            continue
        try:
            if agent_is_tree_child(row):
                continue
        except Exception:  # noqa: BLE001 - count rather than drop on error.
            pass
        rows_by_key.setdefault(key, []).append(row)

    descriptors: list[AgentTabDescriptor] = []
    for entry in entries:
        key = entry.key
        glyph, label = _split_machine_label(entry.label or "")
        is_default = key.kind == "default" or (
            isinstance(key, AgentTabKey) and key == _default_key()
        )
        if key.kind == "machine" or key.kind == "unresolved_machine":
            glyph = glyph or MACHINE_GLYPH
        elif is_default and machine_mode:
            glyph = glyph or MACHINE_GLYPH
        if key.kind == "named":
            name = key.value
            accent = agent_tab_accent_for_name(
                name,
                config_color=colors.get(name, ""),
                enabled_projects=enabled_projects,
            )
            glyph = icons.get(name, "") or glyph
        elif is_default:
            from sase.ace.tui.widgets.agent_tab_strip import MAIN_LABEL_STYLE

            accent = MAIN_LABEL_STYLE
        else:
            from sase.ace.tui.widgets.agent_tab_strip import MACHINE_GLYPH_STYLE

            accent = MACHINE_GLYPH_STYLE
        tab_rows = rows_by_key.get(key, [])
        try:
            summary = sase_agent_status_counts(tab_rows, unread_ids)
            count, stopped, failed, unread = (
                summary.total,
                summary.stopped,
                summary.failed,
                summary.unread,
            )
        except Exception:  # noqa: BLE001 - a bad row degrades to count 0.
            count, stopped, failed, unread = 0, 0, 0, 0
        raw_health = health.get(key, "ok")
        health_value = (
            raw_health if raw_health in ("ok", "stale", "invalid", "offline") else "ok"
        )
        description = descriptions.get(key.value, "") if key.kind == "named" else ""
        extra = None
        try:
            extra = tooltip_extras.get(key)
        except Exception:  # noqa: BLE001
            extra = None
        if extra:
            description = f"{description} · {extra}" if description else str(extra)
        machine_alias = ""
        if glyph == MACHINE_GLYPH:
            machine_alias = label
        descriptors.append(
            AgentTabDescriptor(
                key=key,
                label=label or entry.label or "tab",
                glyph=glyph,
                accent=accent,
                count=count,
                incomplete=bool(incomplete and count),
                stopped=stopped,
                failed=failed,
                unread=unread,
                health=health_value,  # type: ignore[arg-type]
                has_arrival=key in arrived and key != active_key,
                description=description,
                jump_hint=hints.get(key),
                machine_alias=machine_alias,
                is_default=is_default,
            )
        )
    return tuple(descriptors)


def _default_key() -> AgentTabKey:
    """Return the default tab key without importing the mixin graph."""
    from sase.core.agent_tab import DEFAULT_AGENT_TAB_KEY

    return DEFAULT_AGENT_TAB_KEY


def descriptor_signature(
    descriptors: tuple[AgentTabDescriptor, ...],
    active_key: AgentTabKey | None,
    strip_visible: bool,
) -> tuple[Any, ...]:
    """Return the repaint-gating signature for *descriptors*.

    The strip repaints only when the catalog, counts, attention, health,
    active key, or arrival state changes.
    """
    return (
        tuple(
            (
                desc.key,
                desc.label,
                desc.glyph,
                desc.accent,
                desc.count,
                desc.incomplete,
                desc.stopped,
                desc.failed,
                desc.unread,
                desc.health,
                desc.has_arrival,
                desc.jump_hint,
            )
            for desc in descriptors
        ),
        active_key,
        strip_visible,
    )


__all__ = [
    "AgentTabStyleInputs",
    "descriptor_signature",
    "project_agent_tab_descriptors",
    "resolve_agent_tab_style_inputs",
]


@dataclass(frozen=True, slots=True)
class AgentTabStyleInputs:
    """Off-thread-resolved style inputs for descriptor projection.

    Resolved in the worker finalize plan (disk is allowed there) and
    cached by config token; the UI-thread strip refresh only ever reads
    the cached value, so rendering stays free of disk and network work.
    """

    colors: Mapping[str, str] = field(default_factory=dict)
    icons: Mapping[str, str] = field(default_factory=dict)
    descriptions: Mapping[str, str] = field(default_factory=dict)
    enabled_projects: tuple[str, ...] = ()
    machine_mode: bool = False


_STYLE_INPUTS_CACHE: dict[Any, AgentTabStyleInputs] = {}


def resolve_agent_tab_style_inputs(*, allow_disk: bool = False) -> AgentTabStyleInputs:
    """Return cached style inputs, resolving them when allowed.

    With ``allow_disk=False`` (the UI thread) this never touches disk:
    it returns the token-cached value or a config-only fallback (the
    merged config itself is token-cached, so no I/O on hit) with
    hash-only accents. With ``allow_disk=True`` (the worker finalize
    plan) it also resolves the enabled-project accent set from disk and
    refreshes the cache.
    """
    from sase.config import load_merged_config
    from sase.config.core import current_config_token

    try:
        token = current_config_token()
    except Exception:  # noqa: BLE001
        token = ()
    cached = _STYLE_INPUTS_CACHE.get(token, None)
    if cached is not None and (not allow_disk or cached.enabled_projects):
        return cached
    try:
        config = load_merged_config()
    except Exception:  # noqa: BLE001
        return cached or AgentTabStyleInputs()
    ace_cfg = config.get("ace", {}) if isinstance(config, dict) else {}
    try:
        from sase.ace.tui.agent_tabs_settings import (
            agent_tabs_view_config,
            parse_agent_tabs_settings,
        )

        settings = parse_agent_tabs_settings(
            ace_cfg if isinstance(ace_cfg, dict) else {}
        )
        view = agent_tabs_view_config()
        machine_mode = bool(view.machine_mode)
    except Exception:  # noqa: BLE001
        return cached or AgentTabStyleInputs()
    colors = {name: style.color for name, style in settings.tabs.items()}
    icons = {name: style.icon for name, style in settings.tabs.items()}
    descriptions = {name: style.description for name, style in settings.tabs.items()}
    enabled: tuple[str, ...] = ()
    if allow_disk:
        try:
            from sase.core.paths import sase_projects_dir
            from sase.core.project_lifecycle_facade import list_project_records
            from sase.project_accents import accent_among_keys
            from sase.xprompt.loader import get_known_project_workspaces

            try:
                records = list_project_records(sase_projects_dir(), "all")
                enabled = tuple(accent_among_keys(records))
            except Exception:  # noqa: BLE001 - display reads always degrade.
                enabled = tuple(get_known_project_workspaces())
        except Exception:  # noqa: BLE001
            enabled = ()
    resolved = AgentTabStyleInputs(
        colors=colors,
        icons=icons,
        descriptions=descriptions,
        enabled_projects=enabled
        if allow_disk
        else (cached.enabled_projects if cached else ()),
        machine_mode=machine_mode,
    )
    if allow_disk or cached is None:
        _STYLE_INPUTS_CACHE[token] = resolved
        while len(_STYLE_INPUTS_CACHE) > 4:
            _STYLE_INPUTS_CACHE.pop(next(iter(_STYLE_INPUTS_CACHE)))
    return resolved
