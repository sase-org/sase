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
