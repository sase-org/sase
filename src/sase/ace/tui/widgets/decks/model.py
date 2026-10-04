"""Pure deck-panel state model."""

from __future__ import annotations

import dataclasses
from dataclasses import dataclass, field
from enum import StrEnum
from collections.abc import Mapping, Sequence

from sase.ace.tui.util.pane_grid import Axis, PaneGrid


class DeckId(StrEnum):
    """Agent data deck identifier."""

    MAIN = "main"
    FILES = "files"
    TOOLS = "tools"
    FINAL = "final"


class RenderMode(StrEnum):
    """Spread versus paged deck rendering."""

    SPREAD = "spread"
    PAGED = "paged"


DECK_CYCLE: tuple[DeckId, ...] = (
    DeckId.MAIN,
    DeckId.FILES,
    DeckId.TOOLS,
    DeckId.FINAL,
)


class DeckLayout(StrEnum):
    """Deck area split layout."""

    SINGLE = "single"
    TOP_BOTTOM = "top-bottom"
    LEFT_RIGHT = "left-right"


def cycle_deck_id(deck: DeckId, direction: int) -> DeckId:
    """Return the next deck in the active cycle for ``direction`` (wraps).

    Nothing is skipped: empty decks and decks shown in another panel are
    both visited so the order stays predictable.
    """
    from .spec import active_deck_cycle

    cycle = active_deck_cycle()
    index = cycle.index(deck)
    return cycle[(index + direction) % len(cycle)]


def cycle_card_id(
    card_ids: Sequence[str], active: str | None, direction: int
) -> str | None:
    """Return the next card id after ``active`` for ``direction`` (wraps)."""
    if not card_ids:
        return None
    if active is not None and active in card_ids:
        index = list(card_ids).index(active)
    else:
        # Unknown anchor: step from the default card so the keystroke still
        # moves by exactly one card from a sensible neighbor.
        default = _default_card_id(card_ids)
        index = list(card_ids).index(default) if default is not None else -1
        if direction < 0:
            return list(card_ids)[index]
        return list(card_ids)[(index + 1) % len(card_ids)]
    return list(card_ids)[(index + direction) % len(card_ids)]


class DeckView(StrEnum):
    """Deck view policy: automatic or one fixed layout."""

    AUTO = "auto"
    SPREAD = "spread"
    PAGE_CARDS = "page_cards"
    PAGE_BLOCKS = "page_blocks"


DECK_VIEW_CHOICES: tuple[DeckView, ...] = (
    DeckView.AUTO,
    DeckView.SPREAD,
    DeckView.PAGE_CARDS,
    DeckView.PAGE_BLOCKS,
)


@dataclass(frozen=True)
class DeckViewPolicies:
    """Per-panel view policies for the Main and Files decks."""

    main: DeckView = DeckView.AUTO
    files: DeckView = DeckView.AUTO

    def for_deck(self, deck: DeckId) -> DeckView:
        """Return the policy for ``deck``.

        Every deck other than Main/Files (Tools, FINAL) is permanently
        ``AUTO``: no title badge, no ``P``, no persisted key.
        """
        if deck is DeckId.MAIN:
            return self.main
        if deck is DeckId.FILES:
            return self.files
        return DeckView.AUTO

    def with_deck(self, deck: DeckId, view: DeckView) -> DeckViewPolicies:
        """Return a copy with ``deck`` set to ``view``.

        Rejects every deck other than Main/Files (Tools, FINAL) and Files
        ``PAGE_BLOCKS`` with ``ValueError``.
        """
        if deck is DeckId.MAIN:
            return dataclasses.replace(self, main=view)
        if deck is DeckId.FILES:
            if view is DeckView.PAGE_BLOCKS:
                raise ValueError("Files deck cannot use page_blocks")
            return dataclasses.replace(self, files=view)
        raise ValueError(f"{deck.value} deck has no view policy: {view!r}")


@dataclass(frozen=True)
class DeckPanelState:
    """One deck panel's deck and per-deck preferred cards."""

    deck: DeckId
    preferred_cards: dict[DeckId, str] = field(default_factory=dict)
    views: DeckViewPolicies = DeckViewPolicies()
    previous_deck: DeckId | None = None

    @property
    def preferred_card(self) -> str | None:
        """Return Main's preferred card (legacy single-slot view)."""
        return self.preferred_cards.get(DeckId.MAIN)

    def preferred_card_for(self, deck: DeckId) -> str | None:
        """Return the preferred card for ``deck`` (None when unset)."""
        return self.preferred_cards.get(deck)


def _default_panels() -> dict[int, DeckPanelState]:
    """Return the default single-pane session map."""
    return {0: DeckPanelState(DeckId.MAIN)}


@dataclass(frozen=True)
class DeckAreaState:
    """Deck panels on a shared split grid, keyed by stable pane ID."""

    grid: PaneGrid = field(default_factory=PaneGrid)
    panels: Mapping[int, DeckPanelState] = field(default_factory=_default_panels)
    nodes_collapsed: bool = False
    zoom_snapshot: DeckAreaState | None = None

    def __post_init__(self) -> None:
        """Detach the session map so frozen states never share a dict."""
        object.__setattr__(self, "panels", dict(self.panels))

    @property
    def layout(self) -> DeckLayout:
        """Return the outer-axis layout derived from the grid."""
        if len(self.grid.panes) < 2 or self.grid.axis is None:
            return DeckLayout.SINGLE
        if self.grid.axis is Axis.ROWS:
            return DeckLayout.TOP_BOTTOM
        return DeckLayout.LEFT_RIGHT

    @property
    def focused(self) -> int:
        """Return the focused pane ID."""
        return self.grid.focused

    @property
    def ratio(self) -> int:
        """Return the outer first region's share."""
        return self.grid.ratio


SINGLE: DeckAreaState = DeckAreaState()


def panel_state(state: DeckAreaState, pane_id: int) -> DeckPanelState:
    """Return the session for ``pane_id``, raising ``IndexError`` when absent."""
    try:
        return state.panels[pane_id]
    except KeyError:
        raise IndexError(pane_id) from None


def with_panel_deck(state: DeckAreaState, pane_id: int, deck: DeckId) -> DeckAreaState:
    """Return a new state with ``pane_id`` showing ``deck``.

    Records the deck being left as ``previous_deck`` only when the value
    actually changes. A same-deck call returns ``state`` unchanged so a
    follow-up ``show_deck`` of the deck a panel already has cannot invent
    history.
    """
    current = panel_state(state, pane_id)
    if current.deck is deck:
        return state
    panels = dict(state.panels)
    panels[pane_id] = dataclasses.replace(
        current, deck=deck, previous_deck=current.deck
    )
    return dataclasses.replace(state, panels=panels)


def with_preferred_card(
    state: DeckAreaState,
    pane_id: int,
    card_id: str | None,
    deck: DeckId | None = None,
) -> DeckAreaState:
    """Return a new state with ``pane_id`` preferring ``card_id``.

    The preference is stored under ``deck``, which defaults to the panel's
    own deck so cycling on one deck never clobbers another deck's sticky
    card. Deck switches keep the whole mapping (see :func:`with_panel_deck`).
    """
    current = panel_state(state, pane_id)
    target = deck if deck is not None else current.deck
    cards = dict(current.preferred_cards)
    if card_id is None:
        cards.pop(target, None)
    else:
        cards[target] = card_id
    panels = dict(state.panels)
    panels[pane_id] = dataclasses.replace(current, preferred_cards=cards)
    return dataclasses.replace(state, panels=panels)


def with_panel_view(
    state: DeckAreaState, pane_id: int, deck: DeckId, view: DeckView
) -> DeckAreaState:
    """Return a new state with ``pane_id`` holding ``view`` for ``deck``.

    When zoomed, the same pane in ``zoom_snapshot`` is updated as well so
    the change survives unzoom and persistence (which unwraps the zoom).
    """
    current = panel_state(state, pane_id)
    updated_views = current.views.with_deck(deck, view)
    panels = dict(state.panels)
    panels[pane_id] = dataclasses.replace(current, views=updated_views)
    updated = dataclasses.replace(state, panels=panels)
    snapshot = state.zoom_snapshot
    if snapshot is not None and pane_id in snapshot.panels:
        snapshot_views = snapshot.panels[pane_id].views.with_deck(deck, view)
        snapshot_panels = dict(snapshot.panels)
        snapshot_panels[pane_id] = dataclasses.replace(
            snapshot_panels[pane_id], views=snapshot_views
        )
        updated = dataclasses.replace(
            updated,
            zoom_snapshot=dataclasses.replace(snapshot, panels=snapshot_panels),
        )
    return updated


def _default_card_id(card_ids: Sequence[str]) -> str | None:
    """Return the default card: Context, else first, else None."""
    if not card_ids:
        return None
    if "context" in card_ids:
        return "context"
    return card_ids[0]


def resolve_active_card(
    card_ids: Sequence[str],
    preferred: str | None,
    *,
    partial: bool,
) -> str | None:
    """Resolve the active card for a card-document paint.

    Callers pass the shown deck's own preference (see
    :meth:`DeckPanelState.preferred_card_for`) so each deck resolves
    independently.
    """
    if preferred is not None and preferred in card_ids:
        return preferred
    if partial and preferred is not None:
        return None
    return _default_card_id(card_ids)
