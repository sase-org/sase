"""Shared helpers for the agent display mixins."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any, Literal

from sase.core.agent_tribe import public_tribe_name

# Type alias for tab names
TabName = Literal["artifacts", "agents", "services"]

#: Widget id of the reserved ``@default`` panel (internal key ``None``).
#: Named tribes use ``agent-list-panel-{public_tribe_name}`` instead of
#: index slots, so this id is never "whoever is first in sort order."
_MAIN_PANEL_ID = "agent-list-panel"

#: Panel key type — ``None`` for ``@default``; a tribe string otherwise.
PanelKey = str | None


def panel_widget_id_for_key(key: PanelKey) -> str:
    """Return the tribe-stable AgentList widget id for *key*."""
    if key is None:
        return _MAIN_PANEL_ID
    return f"{_MAIN_PANEL_ID}-{public_tribe_name(key)}"


def panel_widget_id(
    panel_idx: int,
    panel_keys: Sequence[PanelKey] | None = None,
) -> str:
    """Return the AgentList widget id for the panel at *panel_idx*.

    When *panel_keys* is provided, the id is tribe-stable for that slot.
    Index-only calls cannot map a tribe and only treat index 0 as the
    reserved default panel.
    """
    if panel_keys is not None:
        return panel_widget_id_for_key(panel_keys[panel_idx])
    if panel_idx == 0:
        return _MAIN_PANEL_ID
    return f"{_MAIN_PANEL_ID}-{panel_idx}"


#: Attribute marking an AgentList whose panel key retired but whose Textual
#: prune has not landed yet. ``widget.remove()`` only schedules the prune, so
#: the widget stays a child of ``#agent-list-container`` for at least one more
#: pump; the marker lets every reader observe the post-retirement panel set
#: in the same refresh frame instead. Test fakes tolerate the plain attribute
#: the way they tolerate the existing ``remove``/``children`` fallback.
_PANEL_RETIRING_ATTR = "_sase_panel_retiring"


def panel_widget_is_retiring(widget: object) -> bool:
    """Return whether *widget* is a retired panel awaiting its prune.

    Identity-compared against ``True`` (rather than truthiness) so mock
    widgets in tests, where every attribute access yields a truthy mock, are
    never mistaken for retiring panels. Only :func:`mark_panel_widget_retiring`
    sets this marker, always to ``True``.
    """
    return getattr(widget, _PANEL_RETIRING_ATTR, False) is True


def mark_panel_widget_retiring(widget: object) -> None:
    """Mark *widget* retired; guarded for test fakes."""
    try:
        setattr(widget, _PANEL_RETIRING_ATTR, True)
    except Exception:
        pass


def agent_list_widgets_in(
    container: object, *, include_retiring: bool = False
) -> list[Any]:
    """Return AgentList children of *container* in visual order.

    Retiring widgets (see :func:`mark_panel_widget_retiring`) are skipped by
    default so reorder, width settle, focus, and the paint log all see the
    post-retirement panel set. Pass ``include_retiring=True`` only to observe
    the still-mounted set, e.g. the id map in
    ``_sync_mounted_panel_widgets`` which must not mount a duplicate id while
    the prune is pending.
    """
    from textual.css.query import NoMatches

    from ...widgets import AgentList

    try:
        widgets = list(
            container.query(AgentList).results(AgentList)  # type: ignore[attr-defined]
        )
    except (AttributeError, TypeError, NoMatches):
        widgets = [
            widget
            for widget in getattr(container, "children", [])
            if isinstance(widget, AgentList)
            or (
                getattr(widget, "id", None)
                and str(widget.id).startswith(_MAIN_PANEL_ID)
            )
        ]
    if include_retiring:
        return widgets
    return [widget for widget in widgets if not panel_widget_is_retiring(widget)]


def first_agent_list_widget(app: object) -> Any | None:
    """Return one mounted AgentList, preferring container children.

    Callers that meant "some Agents-tab list" (loading spinner, focus
    restore) must not assume the reserved default id is occupied.
    """
    from textual.css.query import NoMatches

    from ...widgets import AgentList

    query_one = getattr(app, "query_one", None)
    if not callable(query_one):
        return None
    try:
        container = query_one("#agent-list-container")
    except (NoMatches, KeyError, Exception):
        container = None
    if container is not None:
        widgets = agent_list_widgets_in(container)
        if widgets:
            return widgets[0]
    try:
        widget = query_one(f"#{_MAIN_PANEL_ID}", AgentList)
    except (NoMatches, KeyError, Exception):
        return None
    return None if panel_widget_is_retiring(widget) else widget


def agents_archive_is_active(owner: Any) -> bool:
    """Return whether the Agents tab is showing Archive, without imports."""
    return (
        getattr(getattr(owner, "_agents_archive_view", None), "active_view", None)
        == "archive"
    )


def agents_inbox_detail_allowed(owner: Any) -> bool:
    """Return whether Inbox-originated detail rendering may paint.

    The Inbox path is a single attribute read. The Archive path loads the
    view module only when Archive is actually showing, so it can honor the
    beta flag.
    """
    if not agents_archive_is_active(owner):
        return True
    from ._archive_view import agents_inbox_detail_allowed as impl

    return impl(owner)


def cancel_inbox_detail_debounce(owner: Any) -> bool:
    """Cancel the pending Inbox detail debounce, never an Archive hydration."""
    if agents_archive_is_active(owner):
        from ._archive_view import cancel_inbox_detail_debounce as impl

        return impl(owner)
    debouncer = getattr(owner, "_agent_detail_debouncer", None)
    cancel = getattr(debouncer, "cancel", None)
    if not callable(cancel):
        return False
    cancel()
    return True


def schedule_owned_inbox_detail_update(owner: Any) -> None:
    """Record a fresh owner token, then schedule the shared detail debouncer."""
    from ._archive_view import schedule_owned_inbox_detail_update as impl

    impl(owner)


def scheduled_agents_detail_is_current(owner: Any) -> bool:
    """Return whether the pending debounced update still owns the panel."""
    from ._archive_view import scheduled_agents_detail_is_current as impl

    return impl(owner)


def route_archive_key_if_active(owner: Any, intent: str) -> bool:
    """Route an Archive list key. False on Inbox without importing Archive."""
    if getattr(owner, "current_tab", "agents") != "agents":
        return False
    if not agents_archive_is_active(owner):
        return False
    from ._archive_view import route_archive_key

    return route_archive_key(owner, intent)
