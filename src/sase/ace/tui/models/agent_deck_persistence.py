"""Versioned persistence for the Agents-tab deck layout.

The TUI owns lifecycle scheduling; this module is deliberately synchronous and
side-effect free except for its explicit load/save functions so callers can run
all file and JSON work through ``asyncio.to_thread``.

Schema version 1 stores ``{layout, ratio, focused, nodes_collapsed, panels}``
where each panel entry is ``{deck, preferred_card, preferred_cards, views}``
with the additive optional ``preferred_cards`` object mapping deck names to
card ids and the additive optional ``views`` object ``{main, files}`` holding
per-deck view policies. A three-panel state also writes the additive
optional ``pair`` object ``{region, ratio}`` naming the inner split. The
legacy ``preferred_card`` key is still written and read as Main's preference
so older files keep their sticky Main card. A zoomed session persists its
restored geometry plus the edits made while zoomed. Loading fails
open: unknown decks or layouts fall back to their defaults while the rest of
the file still applies. Unknown deck keys and invalid ``preferred_cards``
entries are skipped; a missing, non-object, or unknown-valued ``views``
decodes to ``AUTO``; Files ``page_blocks`` decodes to ``AUTO``. An older
reader ignores ``pair`` and truncates to two panels, which is still a valid
two-pane split; a malformed ``pair`` recovers to a smaller valid layout with
a warning and never crashes.
"""

from __future__ import annotations

import json
import logging
import os
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from sase.core.paths import sase_home

from ..widgets.decks.layout import RATIO_STEPS
from ..widgets.decks.model import (
    DeckAreaState,
    DeckId,
    DeckLayout,
    DeckPanelState,
    DeckView,
    DeckViewPolicies,
)

log = logging.getLogger(__name__)

SCHEMA_VERSION = 1
FILENAME = "ace_agents_deck_state.json"
MAX_FILE_BYTES = 64 * 1024
MAX_PANELS = 3
MAX_CARD_ID_LENGTH = 256


@dataclass(frozen=True)
class _DeckPanelSnapshot:
    """Persisted deck and per-deck preferred cards for one deck panel."""

    deck: DeckId = DeckId.MAIN
    preferred_cards: dict[DeckId, str] = field(default_factory=dict)
    views: DeckViewPolicies = DeckViewPolicies()

    @property
    def preferred_card(self) -> str | None:
        """Return Main's preferred card (the legacy ``preferred_card`` key)."""
        return self.preferred_cards.get(DeckId.MAIN)


@dataclass(frozen=True)
class AgentsDeckStateSnapshot:
    """Complete persisted Agents-tab deck layout.

    ``pair_region``/``pair_ratio`` name the inner split of a three-panel
    state; both are None/ignored unless exactly three panels persist.
    """

    layout: DeckLayout = DeckLayout.SINGLE
    ratio: int = 50
    focused: int = 0
    nodes_collapsed: bool = False
    panels: tuple[_DeckPanelSnapshot, ...] = (_DeckPanelSnapshot(),)
    pair_region: int | None = None
    pair_ratio: int = 50


EMPTY_AGENTS_DECK_STATE = AgentsDeckStateSnapshot()


class _AgentsDeckStateDecodeError(ValueError):
    """Raised internally when a persisted snapshot fails validation."""


def _agents_deck_state_path() -> Path:
    """Return the global ACE Agents-deck state path."""
    return sase_home() / FILENAME


def _decode_deck(raw: Any) -> DeckId:
    try:
        return DeckId(str(raw))
    except ValueError:
        raise _AgentsDeckStateDecodeError(f"unknown deck: {raw!r}") from None


def _decode_layout(raw: Any) -> DeckLayout:
    try:
        return DeckLayout(str(raw))
    except ValueError:
        raise _AgentsDeckStateDecodeError(f"unknown layout: {raw!r}") from None


def _decode_view(raw: Any) -> DeckView:
    try:
        return DeckView(str(raw))
    except ValueError:
        return DeckView.AUTO


def _decode_views(raw: Any) -> DeckViewPolicies:
    if not isinstance(raw, dict):
        return DeckViewPolicies()
    main = _decode_view(raw.get("main", DeckView.AUTO.value))
    files = _decode_view(raw.get("files", DeckView.AUTO.value))
    if files is DeckView.PAGE_BLOCKS:
        files = DeckView.AUTO
    return DeckViewPolicies(main=main, files=files)


def _decode_card_id(raw: Any) -> str | None:
    """Return ``raw`` when it is a usable card id, else None."""
    if not isinstance(raw, str) or not raw or len(raw) > MAX_CARD_ID_LENGTH:
        return None
    return raw


def _decode_preferred_cards(raw: Any) -> dict[DeckId, str]:
    """Decode the ``preferred_cards`` map, skipping unknown decks and bad ids.

    Keys for decks outside the active cycle are kept so the preference
    survives until that deck registers.
    """
    cards: dict[DeckId, str] = {}
    if not isinstance(raw, dict):
        return cards
    for key, value in raw.items():
        try:
            deck = DeckId(str(key))
        except ValueError:
            continue
        card_id = _decode_card_id(value)
        if card_id is None:
            continue
        cards[deck] = card_id
    return cards


def _decode_panel(raw: Any) -> _DeckPanelSnapshot:
    from ..widgets.decks.spec import active_deck_cycle

    if not isinstance(raw, dict):
        raise _AgentsDeckStateDecodeError("panel must be an object")
    deck = _decode_deck(raw.get("deck", DeckId.MAIN.value))
    if deck not in active_deck_cycle():
        log.warning("Ignoring inactive deck in persisted deck state: %r", deck)
        deck = DeckId.MAIN
    cards = _decode_preferred_cards(raw.get("preferred_cards", None))
    legacy = _decode_card_id(raw.get("preferred_card", None))
    if legacy is None and "preferred_card" in raw and raw["preferred_card"] is not None:
        raise _AgentsDeckStateDecodeError("invalid preferred card")
    if legacy is not None and DeckId.MAIN not in cards:
        cards[DeckId.MAIN] = legacy
    views = _decode_views(raw.get("views", None))
    return _DeckPanelSnapshot(deck=deck, preferred_cards=cards, views=views)


def _decode_pair(raw: Any) -> tuple[int, int] | None:
    """Decode the additive optional ``pair`` object, or None when absent.

    Returns the ``(region, ratio)`` pair, or None when ``raw`` is missing
    (a two-panel file, or an old writer). Raises
    :class:`_AgentsDeckStateDecodeError` on a malformed present value so
    the caller can recover to a smaller valid layout with a warning.
    """
    if raw is None:
        return None
    if not isinstance(raw, dict):
        raise _AgentsDeckStateDecodeError("pair must be an object")
    region = raw.get("region", None)
    pair_ratio = raw.get("ratio", 50)
    if region not in (0, 1) or pair_ratio not in RATIO_STEPS:
        raise _AgentsDeckStateDecodeError(f"invalid pair: {raw!r}")
    return (region, pair_ratio)


def _decode_agents_deck_state(decoded: Any) -> AgentsDeckStateSnapshot:
    if not isinstance(decoded, dict):
        raise _AgentsDeckStateDecodeError("deck state must be an object")
    schema_version = decoded.get("schema_version", SCHEMA_VERSION)
    if schema_version != SCHEMA_VERSION:
        raise _AgentsDeckStateDecodeError(
            f"unsupported schema version: {schema_version!r}"
        )
    try:
        layout = _decode_layout(decoded.get("layout", DeckLayout.SINGLE.value))
    except _AgentsDeckStateDecodeError:
        log.warning("Ignoring unknown deck layout in persisted deck state")
        layout = DeckLayout.SINGLE
    ratio = decoded.get("ratio", 50)
    if ratio not in RATIO_STEPS:
        ratio = 50
    nodes_collapsed = decoded.get("nodes_collapsed", False)
    if not isinstance(nodes_collapsed, bool):
        nodes_collapsed = False
    raw_panels = decoded.get("panels", [{"deck": DeckId.MAIN.value}])
    if not isinstance(raw_panels, list) or not raw_panels:
        raise _AgentsDeckStateDecodeError("panels must be a non-empty list")
    panels: list[_DeckPanelSnapshot] = []
    for raw in raw_panels[:MAX_PANELS]:
        try:
            panels.append(_decode_panel(raw))
        except _AgentsDeckStateDecodeError:
            log.warning("Ignoring unknown deck in persisted deck state")
            panels.append(_DeckPanelSnapshot())
    if layout is DeckLayout.SINGLE:
        panels = panels[:1]
    try:
        pair = _decode_pair(decoded.get("pair", None))
    except _AgentsDeckStateDecodeError:
        log.warning("Ignoring malformed pair in persisted deck state")
        pair = None
        if len(panels) > 2:
            panels = panels[:2]
    if len(panels) > 2 and pair is None:
        log.warning("Ignoring unpaired third panel in persisted deck state")
        panels = panels[:2]
    if len(panels) <= 2:
        pair = None
    focused = decoded.get("focused", 0)
    if not isinstance(focused, int) or focused < 0 or focused >= len(panels):
        focused = 0
    return AgentsDeckStateSnapshot(
        layout=layout,
        ratio=ratio,
        focused=focused,
        nodes_collapsed=nodes_collapsed,
        panels=tuple(panels),
        pair_region=pair[0] if pair is not None else None,
        pair_ratio=pair[1] if pair is not None else 50,
    )


def snapshot_from_area_state(state: DeckAreaState) -> AgentsDeckStateSnapshot:
    """Capture ``state`` for persistence, unwrapping any zoom snapshot.

    Panels are written in grid reading order with ``focused`` as the
    reading-order index; the zoomed pane's edits persist through the
    restored geometry. A three-panel state also records the inner split
    as ``pair``.
    """
    from sase.ace.tui.util.pane_grid import Pair

    from ..widgets.decks.layout import exit_zoom_keeping_panels

    if state.zoom_snapshot is not None:
        effective = exit_zoom_keeping_panels(state)
    else:
        effective = state
    order = list(effective.grid.panes[:MAX_PANELS])
    panels = tuple(
        _DeckPanelSnapshot(
            deck=effective.panels[pane_id].deck,
            preferred_cards=dict(effective.panels[pane_id].preferred_cards),
            views=effective.panels[pane_id].views,
        )
        for pane_id in order
        if pane_id in effective.panels
    ) or (_DeckPanelSnapshot(),)
    layout = effective.layout
    if layout is DeckLayout.SINGLE:
        panels = panels[:1]
    try:
        focused = list(effective.grid.panes).index(effective.grid.focused)
    except ValueError:
        focused = 0
    if focused < 0 or focused >= len(panels):
        focused = 0
    ratio = effective.ratio if effective.ratio in RATIO_STEPS else 50
    pair: Pair | None = effective.grid.pair
    if len(panels) != 3 or pair is None or pair.region not in (0, 1):
        pair_region: int | None = None
        pair_ratio = 50
    else:
        pair_region = pair.region
        pair_ratio = pair.ratio if pair.ratio in RATIO_STEPS else 50
    return AgentsDeckStateSnapshot(
        layout=layout,
        ratio=ratio,
        focused=focused,
        nodes_collapsed=bool(effective.nodes_collapsed),
        panels=panels,
        pair_region=pair_region,
        pair_ratio=pair_ratio,
    )


def area_state_from_snapshot(snapshot: AgentsDeckStateSnapshot) -> DeckAreaState:
    """Rebuild deck-area state from ``snapshot`` (no zoom snapshot).

    Pane IDs ``0..n-1`` are assigned in reading order.
    """
    from sase.ace.tui.util.pane_grid import Axis, Pair, PaneGrid

    items = list(snapshot.panels) or [_DeckPanelSnapshot()]
    if snapshot.layout is DeckLayout.SINGLE:
        items = items[:1]
    items = items[:MAX_PANELS]
    order = list(range(len(items)))
    panels = {
        pane_id: DeckPanelState(
            deck=item.deck,
            preferred_cards=dict(item.preferred_cards),
            views=item.views,
        )
        for pane_id, item in zip(order, items, strict=True)
    }
    if not panels:
        panels = {0: DeckPanelState(DeckId.MAIN)}
        order = [0]
    focused_index = snapshot.focused
    if focused_index < 0 or focused_index >= len(order):
        focused_index = 0
    focused_id = order[focused_index]
    if len(order) < 2:
        grid = PaneGrid(panes=(focused_id,), focused=focused_id, recent=(focused_id,))
    else:
        axis = Axis.COLS if snapshot.layout is DeckLayout.LEFT_RIGHT else Axis.ROWS
        ratio = snapshot.ratio if snapshot.ratio in RATIO_STEPS else 50
        recent = (focused_id, *(pid for pid in order if pid != focused_id))
        if len(order) == 2:
            grid = PaneGrid(
                panes=tuple(order),
                focused=focused_id,
                axis=axis,
                ratio=ratio,
                recent=recent,
            )
        else:
            region = snapshot.pair_region if snapshot.pair_region in (0, 1) else 1
            pair_ratio = (
                snapshot.pair_ratio if snapshot.pair_ratio in RATIO_STEPS else 50
            )
            grid = PaneGrid(
                panes=tuple(order),
                focused=focused_id,
                axis=axis,
                ratio=ratio,
                pair=Pair(region=region, ratio=pair_ratio),
                recent=recent,
            )
    return DeckAreaState(
        grid=grid,
        panels=panels,
        nodes_collapsed=bool(snapshot.nodes_collapsed),
    )


def _serialize_agents_deck_state(snapshot: AgentsDeckStateSnapshot) -> str:
    decoded: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "layout": snapshot.layout.value,
        "ratio": snapshot.ratio,
        "focused": snapshot.focused,
        "nodes_collapsed": snapshot.nodes_collapsed,
        "panels": [
            {
                "deck": item.deck.value,
                "preferred_card": item.preferred_card,
                "preferred_cards": {
                    deck.value: card_id
                    for deck, card_id in item.preferred_cards.items()
                },
                "views": {
                    "main": item.views.main.value,
                    "files": item.views.files.value,
                },
            }
            for item in snapshot.panels
        ],
    }
    if len(snapshot.panels) == 3 and snapshot.pair_region in (0, 1):
        decoded["pair"] = {
            "region": snapshot.pair_region,
            "ratio": snapshot.pair_ratio if snapshot.pair_ratio in RATIO_STEPS else 50,
        }
    serialized = (
        json.dumps(
            decoded,
            separators=(",", ":"),
            sort_keys=True,
        )
        + "\n"
    )
    if len(serialized.encode("utf-8")) > MAX_FILE_BYTES:
        raise ValueError("Agents deck state exceeds maximum file size")
    return serialized


def load_agents_deck_state(path: Path | None = None) -> AgentsDeckStateSnapshot:
    """Load and defensively decode the deck snapshot, failing open to empty."""
    state_path = path or _agents_deck_state_path()
    try:
        with state_path.open("rb") as stream:
            raw_bytes = stream.read(MAX_FILE_BYTES + 1)
    except FileNotFoundError:
        log.debug("Agents deck state is missing: %s", state_path)
        return EMPTY_AGENTS_DECK_STATE
    except OSError:
        log.warning("Unable to read Agents deck state: %s", state_path, exc_info=True)
        return EMPTY_AGENTS_DECK_STATE
    if len(raw_bytes) > MAX_FILE_BYTES:
        log.warning("Ignoring oversized Agents deck state: %s", state_path)
        return EMPTY_AGENTS_DECK_STATE
    try:
        decoded = json.loads(raw_bytes.decode("utf-8"))
        return _decode_agents_deck_state(decoded)
    except (UnicodeDecodeError, json.JSONDecodeError, _AgentsDeckStateDecodeError):
        log.warning(
            "Ignoring malformed Agents deck state: %s", state_path, exc_info=True
        )
        return EMPTY_AGENTS_DECK_STATE


def save_agents_deck_state(
    snapshot: AgentsDeckStateSnapshot,
    path: Path | None = None,
) -> None:
    """Atomically save *snapshot* using a same-directory temporary file."""
    state_path = path or _agents_deck_state_path()
    payload = _serialize_agents_deck_state(snapshot)
    state_path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(
        dir=state_path.parent,
        prefix=f".{state_path.name}.",
        suffix=".tmp",
    )
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            stream.write(payload)
            stream.flush()
            try:
                os.fsync(stream.fileno())
            except OSError:
                pass
        os.replace(temporary, state_path)
    except Exception:
        try:
            os.unlink(temporary)
        except OSError:
            pass
        raise


__all__ = [
    "AgentsDeckStateSnapshot",
    "EMPTY_AGENTS_DECK_STATE",
    "FILENAME",
    "MAX_FILE_BYTES",
    "MAX_PANELS",
    "SCHEMA_VERSION",
    "area_state_from_snapshot",
    "load_agents_deck_state",
    "save_agents_deck_state",
    "snapshot_from_area_state",
]
