"""Tab catalog view, strip visibility, and bulk scope labels (tab-state-keys).

With the ``agent_tabs`` flag off every entry point is a no-op: the scope
stays the default key, no strip appears, and bulk wording stays None so
confirmations stay byte-identical. With the flag on, the catalog view adds
the emptied-tab latch, the strip shows when two or more tabs exist, and the
bulk helpers describe the active scope.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from sase.core.agent_tab import AgentTabKey

from ...agent_tabs_flag import agent_tabs_enabled
from ...models.agent_tab_index import AgentTabCatalogEntry


def _fallback_label(key: AgentTabKey) -> str:
    """Return a last-resort strip label for *key*."""
    if key.kind == "named":
        return key.value or "tab"
    if key.kind == "machine":
        return f"\u2328 {key.value}"
    return "main"


def catalog_view_for_owner(owner: Any) -> tuple[AgentTabCatalogEntry, ...]:
    """Return the strip's catalog view: index entries plus a latched key.

    The latch keeps an emptied active tab selected with an empty roster, so
    the strip shows the latched key with count 0 until the user navigates
    away or roots return.
    """
    index = getattr(owner, "_agent_tab_index", None)
    entries = tuple(getattr(index, "catalog", ()) or ())
    latched = getattr(owner, "_agent_tab_latched_key", None)
    if (
        isinstance(latched, AgentTabKey)
        and latched.kind != "unresolved_machine"
        and not any(entry.key == latched for entry in entries)
    ):
        label = getattr(owner, "_agent_tab_known_labels", {}).get(latched)
        if not isinstance(label, str) or not label:
            label = _fallback_label(latched)
        entries = (*entries, AgentTabCatalogEntry(latched, latched.kind, label, 0))
    return entries


def active_tab_label_for_owner(owner: Any) -> str:
    """Return the active tab's strip label, falling back to a default."""
    active = getattr(owner, "_active_agent_tab", None)
    for entry in catalog_view_for_owner(owner):
        if entry.key == active and isinstance(entry.label, str) and entry.label:
            return entry.label
    known = getattr(owner, "_agent_tab_known_labels", None)
    if isinstance(known, dict):
        label = known.get(active)
        if isinstance(label, str) and label:
            return label
    if isinstance(active, AgentTabKey):
        return _fallback_label(active)
    return "main"


def strip_visible_for_owner(owner: Any) -> bool:
    """Return True when the minimal tab strip should render.

    Visible iff the flag is on and the catalog view holds two or more tabs,
    or while the emptied-tab latch holds.
    """
    if not agent_tabs_enabled():
        return False
    if getattr(owner, "_agent_tab_latched_key", None) is not None:
        return True
    return len(catalog_view_for_owner(owner)) >= 2


def bulk_scope_label_for_owner(owner: Any) -> str | None:
    """Return the bulk-confirmation scope wording, or None for today's text.

    Returns ``on <tab label>`` (for example ``on sase``) when the flag is on
    and the strip is visible, ``across all tabs`` at the ``ALL_AGENT_TABS``
    scope, and None otherwise. None keeps every confirmation byte-identical.
    """
    if not agent_tabs_enabled():
        return None
    from ...models.agent_tab_index import ALL_AGENT_TABS

    if getattr(owner, "_active_agent_tab", None) is ALL_AGENT_TABS:
        return "across all tabs"
    if not strip_visible_for_owner(owner):
        return None
    return f"on {active_tab_label_for_owner(owner)}"


def marked_off_tab_count_for_owner(owner: Any, agents: list[Any]) -> int:
    """Return how many of *agents* sit off the owner's active tab.

    Returns 0 with the flag off (or without an index), so flag-off
    confirmations stay byte-identical.
    """
    if not agent_tabs_enabled():
        return 0
    index = getattr(owner, "_agent_tab_index", None)
    active = getattr(owner, "_active_agent_tab", None)
    key_for = getattr(index, "key_for", None)
    if index is None or active is None or not callable(key_for):
        return 0
    count = 0
    for agent in agents:
        try:
            if key_for(agent) != active:
                count += 1
        except Exception:
            continue
    return count


def _format_host_issue(issue: Any) -> str:
    """Format one host feed issue the way the fleet status line does."""
    alias = str(getattr(issue, "alias", "") or "")
    label = str(getattr(issue, "status", None) or "error")
    error = getattr(issue, "error", None)
    diagnostic = getattr(issue, "diagnostic", None)
    detail_parts = [
        item for item in (error, diagnostic if diagnostic != error else None) if item
    ]
    detail = (
        f": {' - '.join(str(part) for part in detail_parts)}" if detail_parts else ""
    )
    try:
        age_seconds = getattr(issue, "cache_age_seconds", None)
    except Exception:
        age_seconds = None
    if age_seconds is not None:
        try:
            from ...models.agent import format_compact_duration

            age = format_compact_duration(age_seconds)
        except Exception:
            age = f"{age_seconds}s"
        return f"{alias}: feed {label}{detail} (cached {age} ago)"
    return f"{alias}: feed {label}{detail}"


def agent_tab_health_for_owner(
    owner: Any,
) -> tuple[dict[AgentTabKey, str], dict[AgentTabKey, str], str]:
    """Return ``(health_by_key, tooltip_extras, active_text)`` (no I/O).

    Machine-tab health reuses the fleet projection's host feed issues
    (invalid/offline, red) and diagnostics (stale, amber). The active
    machine tab's issue text doubles as the header's right-side health.
    """
    health: dict[AgentTabKey, str] = {}
    extras: dict[AgentTabKey, str] = {}
    active_text = ""
    try:
        projection = getattr(owner, "_agents_fleet_projection", None)
        issues = tuple(getattr(projection, "host_feed_issues", ()) or ())
        diagnostics = tuple(getattr(projection, "diagnostics", ()) or ())
    except Exception:
        return health, extras, active_text
    if not issues and not diagnostics:
        return health, extras, active_text
    try:
        from ...agent_tabs_settings import agent_tabs_view_config

        view = agent_tabs_view_config()
    except Exception:
        return health, extras, active_text
    alias_by_id = dict(view.machine_order or ())
    issue_by_alias: dict[str, Any] = {}
    for issue in issues:
        try:
            alias = str(getattr(issue, "alias", "") or "")
        except Exception:
            continue
        if alias:
            issue_by_alias.setdefault(alias, issue)
    diag_aliases: set[str] = set()
    for diagnostic in diagnostics:
        try:
            if isinstance(diagnostic, Mapping):
                diag_alias: Any = diagnostic.get("alias")
            else:
                diag_alias = getattr(diagnostic, "alias", "")
        except Exception:
            diag_alias = ""
        if isinstance(diag_alias, str) and diag_alias:
            diag_aliases.add(diag_alias)
    try:
        entries = catalog_view_for_owner(owner)
    except Exception:
        return health, extras, active_text
    for entry in entries:
        key = entry.key
        if not isinstance(key, AgentTabKey):
            continue
        if key.kind == "machine":
            candidates = [alias_by_id.get(key.value, "")]
        elif key.kind == "default" and view.machine_mode:
            candidates = []
        else:
            continue
        try:
            bare = (entry.label or "").removeprefix("\u2328 ").strip()
        except Exception:
            bare = ""
        if bare:
            candidates.append(bare)
        matched_issue = next(
            (issue_by_alias[c] for c in candidates if c in issue_by_alias), None
        )
        if matched_issue is not None:
            health[key] = "invalid"
            extras[key] = _format_host_issue(matched_issue)
            continue
        if any(candidate in diag_aliases for candidate in candidates if candidate):
            health[key] = "stale"
            stale_alias = next(
                candidate for candidate in candidates if candidate in diag_aliases
            )
            extras[key] = f"{stale_alias}: stale"
    try:
        active = getattr(owner, "_active_agent_tab", None)
    except Exception:
        active = None
    if isinstance(active, AgentTabKey) and active in extras:
        active_text = extras[active]
    return health, extras, active_text


__all__ = [
    "active_tab_label_for_owner",
    "agent_tab_health_for_owner",
    "bulk_scope_label_for_owner",
    "catalog_view_for_owner",
    "marked_off_tab_count_for_owner",
    "strip_visible_for_owner",
]
