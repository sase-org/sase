"""Agents-tab Archive per-panel deck parking and list-scroll parking.

Parking seam for the Agents Archive epic (child epic ``sase-1jm.3.1``).
``owner`` is the app, duck-typed so fakes can drive every helper without a
composed widget tree. The lifecycle module consumes the public
``capture_*``/``restore_*`` helpers; the public import path stays
:mod:`sase.ace.tui.actions.agents._archive_view`, which re-exports only
:func:`flush_pending_archive_list_scroll` from here.
"""

from __future__ import annotations

import logging
from typing import Any

from ...models.agent_archive_view import ParkedInboxState
from ._archive_view_state import agents_archive_view_state

log = logging.getLogger(__name__)


def _deck_name(deck: Any) -> str:
    return str(getattr(deck, "value", None) or deck)


def _panel_deck_choices_from_area(area: Any) -> dict[str, str]:
    """Extract per-panel deck and full preferred_cards keyed by real pane id."""
    choices: dict[str, str] = {}
    panels = getattr(getattr(area, "state", None), "panels", None) or {}
    if not isinstance(panels, dict):
        return choices
    for pane_id, panel in panels.items():
        deck = getattr(panel, "deck", None)
        if deck is not None:
            choices[str(pane_id)] = _deck_name(deck)
        preferred_cards = dict(getattr(panel, "preferred_cards", None) or {})
        if not preferred_cards:
            current_card = getattr(panel, "preferred_card", None)
            if current_card and deck is not None:
                preferred_cards = {deck: current_card}
        for deck_id, card in preferred_cards.items():
            choices[f"{pane_id}:card:{_deck_name(deck_id)}"] = str(card)
    return choices


def _panel_deck_choices_from_snapshot(snapshot: Any) -> dict[str, str]:
    """Extract per-panel deck and cards from a snapshot that carries pane ids.

    Splits (layout, ratio) are shared between views and are never parked.
    Reading-order snapshots without pane ids are ignored so decks cannot swap.
    """
    choices: dict[str, str] = {}
    panels = getattr(snapshot, "panels", None)
    if not panels:
        return choices
    if isinstance(panels, dict):
        items = list(panels.items())
    else:
        items = []
        for panel in panels:
            pane_id = getattr(panel, "pane_id", None)
            if pane_id is None:
                continue
            items.append((pane_id, panel))
    for pane_id, panel in items:
        deck = getattr(panel, "deck", None)
        if deck is not None:
            choices[str(pane_id)] = _deck_name(deck)
        preferred_cards = dict(getattr(panel, "preferred_cards", None) or {})
        if not preferred_cards:
            current_card = getattr(panel, "preferred_card", None)
            if current_card and deck is not None:
                preferred_cards = {deck: current_card}
        for deck_id, card in preferred_cards.items():
            choices[f"{pane_id}:card:{_deck_name(deck_id)}"] = str(card)
    return choices


def _capture_detail_scrolls(owner: Any) -> dict[str, str]:
    """Capture each deck panel's scroll offset as ``{pane}:scroll`` entries."""
    scrolls: dict[str, str] = {}
    try:
        from ...widgets import AgentDetail

        detail = owner.query_one("#agent-detail-panel", AgentDetail)
        area = detail.deck_area
        for pane_id in getattr(area.state, "panels", {}):
            try:
                scroller = area.panel(pane_id).active_scroll()
                scrolls[f"{pane_id}:scroll"] = str(
                    float(getattr(scroller, "scroll_y", 0.0) or 0.0)
                )
            except Exception:
                continue
    except Exception:
        return scrolls
    return scrolls


def _live_deck_area(owner: Any) -> Any | None:
    try:
        from ...widgets import AgentDetail

        return owner.query_one("#agent-detail-panel", AgentDetail).deck_area
    except Exception:
        return None


def _capture_per_panel_parking(owner: Any) -> dict[str, str]:
    """Capture each panel's deck, full preferred_cards, and scroll."""
    choices: dict[str, str] = {}
    area = _live_deck_area(owner)
    if area is not None:
        choices.update(_panel_deck_choices_from_area(area))
    else:
        try:
            capture = getattr(owner, "_capture_agents_deck_state", None)
            snapshot = capture() if callable(capture) else None
        except Exception:
            snapshot = None
        choices.update(_panel_deck_choices_from_snapshot(snapshot))
    choices.update(_capture_detail_scrolls(owner))
    return choices


def _parked_pane_ids(choices: dict[str, str]) -> list[int]:
    ids: set[int] = set()
    for key in choices:
        head = key.split(":", 1)[0]
        if head.isdigit():
            ids.add(int(head))
    return sorted(ids)


def _restore_per_panel_deck_choices(owner: Any, choices: dict[str, str]) -> None:
    """Restore each panel's deck, full preferred_cards, and scroll."""
    if not choices:
        return
    try:
        from ...widgets import AgentDetail
        from ...widgets.decks.model import DeckId

        detail = owner.query_one("#agent-detail-panel", AgentDetail)
    except Exception:
        return
    for pane_id in _parked_pane_ids(choices):
        deck_name = choices.get(str(pane_id))
        if deck_name:
            try:
                detail.show_deck(pane_id, DeckId(deck_name))
            except Exception:
                log.debug("could not restore parked deck %s", deck_name, exc_info=True)
        cards: dict[Any, str] = {}
        prefix = f"{pane_id}:card:"
        for key, value in choices.items():
            if key.startswith(prefix):
                try:
                    cards[DeckId(key[len(prefix) :])] = value
                except Exception:
                    continue
        if cards:
            try:
                detail.deck_area.set_preferred_cards(pane_id, cards)
            except Exception:
                log.debug(
                    "could not restore parked cards for pane %s", pane_id, exc_info=True
                )
        scroll_raw = choices.get(f"{pane_id}:scroll")
        if scroll_raw:
            try:
                detail.deck_area.panel(pane_id).active_scroll().scroll_y = float(
                    scroll_raw
                )
            except Exception:
                log.debug("could not restore parked deck scroll", exc_info=True)


def _capture_archive_list_scroll(owner: Any) -> int:
    """Capture the Archive list's scroll offset."""
    try:
        widget = owner.query_one("#archive-list")
        return int(getattr(widget, "scroll_y", 0) or 0)
    except Exception:
        return int(getattr(agents_archive_view_state(owner).archive, "scroll", 0) or 0)


def _restore_archive_list_scroll(owner: Any, scroll: int) -> None:
    """Restore the Archive list's scroll offset, clamped to max scroll."""
    if not scroll:
        return
    try:
        widget = owner.query_one("#archive-list")
        max_y = getattr(widget, "max_scroll_y", None)
        try:
            max_y = int(max_y) if max_y is not None else 0
        except Exception:
            max_y = 0
        widget.scroll_y = min(scroll, max_y) if max_y else scroll
    except Exception:
        pass


def flush_pending_archive_list_scroll(owner: Any) -> None:
    """Apply a parked Archive list scroll after the list has rows."""
    scroll = int(getattr(owner, "_pending_archive_list_scroll", 0) or 0)
    owner._pending_archive_list_scroll = 0
    if not scroll:
        return

    def _apply() -> None:
        _restore_archive_list_scroll(owner, scroll)

    after = getattr(owner, "call_after_refresh", None)
    if callable(after):
        after(_apply)
    else:
        _apply()


def capture_archive_parking(owner: Any) -> None:
    """Park Archive per-panel deck, card, and scroll before leaving."""
    archive = agents_archive_view_state(owner).archive
    archive.deck_choices = _capture_per_panel_parking(owner)
    archive.scroll = _capture_archive_list_scroll(owner)


def restore_archive_parking(owner: Any) -> None:
    """Restore Archive per-panel deck and card; delay list scroll until rows."""
    archive = agents_archive_view_state(owner).archive
    _restore_per_panel_deck_choices(owner, archive.deck_choices)
    owner._pending_archive_list_scroll = int(archive.scroll or 0)


def capture_parked_inbox(owner: Any) -> ParkedInboxState:
    """Snapshot the Inbox state parked while the Archive is active."""
    selector = getattr(owner, "_get_selected_agent", None)
    agent = selector() if callable(selector) else None
    scroll_y = 0.0
    focused_panel = None
    try:
        from ...widgets import AgentList

        list_widget = owner.query_one("#agent-list-panel", AgentList)
        scroll_y = float(getattr(list_widget, "scroll_y", 0.0) or 0.0)
    except Exception:
        pass
    try:
        focused = getattr(owner, "_resolve_focused_panel", lambda: None)()
        if focused is not None:
            key = getattr(focused, "panel_key", None)
            if key is None:
                key = getattr(focused, "key", None)
            # Empty string encodes the reserved default panel (key None);
            # a missing focus stays None so restore is a no-op.
            focused_panel = "" if key is None else str(key)
    except Exception:
        pass
    folds: tuple[Any, ...] = ()
    try:
        snapshot = getattr(
            getattr(owner, "_group_fold_registry", None), "snapshot", None
        )
        if callable(snapshot):
            folds = tuple(snapshot())
    except Exception:
        pass
    deck_state = None
    try:
        capture = getattr(owner, "_capture_agents_deck_state", None)
        deck_state = capture() if callable(capture) else None
    except Exception:
        pass
    deck_choices = _capture_per_panel_parking(owner)
    if not any(
        key.split(":", 1)[0].isdigit() and ":" not in key for key in deck_choices
    ):
        extra = _panel_deck_choices_from_snapshot(deck_state)
        extra.update(deck_choices)
        deck_choices = extra
    return ParkedInboxState(
        committed_query=str(getattr(owner, "_agent_search_query", "") or ""),
        selected_identity=getattr(agent, "identity", None),
        scroll=int(getattr(owner, "current_idx", 0) or 0),
        scroll_y=scroll_y,
        agent_tab=getattr(owner, "_active_agent_tab", None),
        panel_focus=getattr(getattr(owner, "focused", None), "id", None),
        panel_layout=getattr(owner, "_agent_panels_grouped", None),
        focused_panel=focused_panel,
        group_focus=getattr(owner, "_current_group_key", None),
        deck_state=deck_state,
        deck_choices=deck_choices,
        folds=folds,
    )


def restore_parked_inbox(owner: Any, parked: ParkedInboxState) -> None:
    """Restore the Inbox cursor, tab, scroll, panel and fold state."""
    if hasattr(owner, "_agent_search_query"):
        owner._agent_search_query = parked.committed_query
    agents = list(getattr(owner, "_agents", ()) or [])
    if parked.selected_identity is not None:
        for index, agent in enumerate(agents):
            if getattr(agent, "identity", None) == parked.selected_identity:
                owner.current_idx = index
                break
        else:
            owner.current_idx = max(0, min(parked.scroll, max(0, len(agents) - 1)))
    elif hasattr(owner, "current_idx"):
        owner.current_idx = parked.scroll
    if parked.agent_tab is not None:
        owner._active_agent_tab = parked.agent_tab
    if parked.group_focus is not None or hasattr(owner, "_current_group_key"):
        owner._current_group_key = parked.group_focus
    registry = getattr(owner, "_group_fold_registry", None)
    restore_folds = getattr(registry, "restore", None)
    if callable(restore_folds):
        try:
            restore_folds(parked.folds)
        except Exception:
            log.debug("could not restore parked Inbox folds", exc_info=True)
    if parked.panel_layout is not None and hasattr(owner, "_agent_panels_grouped"):
        owner._agent_panels_grouped = bool(parked.panel_layout)
    if parked.focused_panel is not None:
        panel_group = getattr(owner, "_panel_group", None)
        keys = list(getattr(panel_group, "panel_keys", ()) or ())
        target: Any = parked.focused_panel or None
        if panel_group is not None and target in keys:
            try:
                panel_group.focused_idx = keys.index(target)
                from ._panel_fold_intent import panel_is_collapsed

                owner._expanded_panel_focus = not panel_is_collapsed(owner, target)
            except Exception:
                log.debug("could not restore parked Inbox panel focus", exc_info=True)
    deck_choices = parked.deck_choices or _panel_deck_choices_from_snapshot(
        parked.deck_state
    )
    # Splits are shared: restore only each panel's deck, card, and scroll.
    _restore_per_panel_deck_choices(owner, deck_choices)
    if parked.panel_focus:
        try:
            owner.query_one(f"#{parked.panel_focus}").focus()
        except Exception:
            pass
    if parked.scroll_y:
        try:
            from ...widgets import AgentList

            owner.query_one("#agent-list-panel", AgentList).scroll_y = parked.scroll_y
        except Exception:
            pass


__all__ = [
    "capture_archive_parking",
    "capture_parked_inbox",
    "flush_pending_archive_list_scroll",
    "restore_archive_parking",
    "restore_parked_inbox",
]
