"""Versioned persistence for the Agents-tab deck layout.

The TUI owns lifecycle scheduling; this module is deliberately synchronous and
side-effect free except for its explicit load/save functions so callers can run
all file and JSON work through ``asyncio.to_thread``.

Schema version 1 stores ``{layout, ratio, focused, nodes_collapsed, panels}``
where each panel entry is ``{deck, preferred_card}``. A zoomed session persists
its pre-zoom snapshot, so callers must pass the effective (unzoomed) state via
:func:`snapshot_from_area_state`. Loading fails open: unknown decks or layouts
fall back to their defaults while the rest of the file still applies.
"""

from __future__ import annotations

import json
import logging
import os
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from sase.core.paths import sase_home

from ..widgets.decks.layout import RATIO_STEPS
from ..widgets.decks.model import (
    DeckAreaState,
    DeckId,
    DeckLayout,
    DeckPanelState,
)

log = logging.getLogger(__name__)

SCHEMA_VERSION = 1
FILENAME = "ace_agents_deck_state.json"
MAX_FILE_BYTES = 64 * 1024
MAX_PANELS = 2
MAX_CARD_ID_LENGTH = 256


@dataclass(frozen=True)
class _DeckPanelSnapshot:
    """Persisted deck and preferred card for one deck panel."""

    deck: DeckId = DeckId.MAIN
    preferred_card: str | None = None


@dataclass(frozen=True)
class AgentsDeckStateSnapshot:
    """Complete persisted Agents-tab deck layout."""

    layout: DeckLayout = DeckLayout.SINGLE
    ratio: int = 50
    focused: int = 0
    nodes_collapsed: bool = False
    panels: tuple[_DeckPanelSnapshot, ...] = (_DeckPanelSnapshot(),)


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


def _decode_panel(raw: Any) -> _DeckPanelSnapshot:
    if not isinstance(raw, dict):
        raise _AgentsDeckStateDecodeError("panel must be an object")
    deck = _decode_deck(raw.get("deck", DeckId.MAIN.value))
    preferred = raw.get("preferred_card")
    if preferred is not None and (
        not isinstance(preferred, str)
        or not preferred
        or len(preferred) > MAX_CARD_ID_LENGTH
    ):
        raise _AgentsDeckStateDecodeError("invalid preferred card")
    return _DeckPanelSnapshot(deck, preferred)


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
    focused = decoded.get("focused", 0)
    if not isinstance(focused, int) or focused < 0 or focused >= len(panels):
        focused = 0
    return AgentsDeckStateSnapshot(
        layout=layout,
        ratio=ratio,
        focused=focused,
        nodes_collapsed=nodes_collapsed,
        panels=tuple(panels),
    )


def snapshot_from_area_state(state: DeckAreaState) -> AgentsDeckStateSnapshot:
    """Capture ``state`` for persistence, unwrapping any zoom snapshot."""
    effective = state.zoom_snapshot if state.zoom_snapshot is not None else state
    panels = tuple(
        _DeckPanelSnapshot(panel.deck, panel.preferred_card)
        for panel in effective.panels[:MAX_PANELS]
    ) or (_DeckPanelSnapshot(),)
    layout = effective.layout
    if layout is DeckLayout.SINGLE:
        panels = panels[:1]
    focused = effective.focused
    if focused < 0 or focused >= len(panels):
        focused = 0
    ratio = effective.ratio if effective.ratio in RATIO_STEPS else 50
    return AgentsDeckStateSnapshot(
        layout=layout,
        ratio=ratio,
        focused=focused,
        nodes_collapsed=bool(effective.nodes_collapsed),
        panels=panels,
    )


def area_state_from_snapshot(snapshot: AgentsDeckStateSnapshot) -> DeckAreaState:
    """Rebuild deck-area state from ``snapshot`` (no zoom snapshot)."""
    panels = tuple(
        DeckPanelState(item.deck, item.preferred_card) for item in snapshot.panels
    ) or (DeckPanelState(DeckId.MAIN),)
    if snapshot.layout is DeckLayout.SINGLE:
        panels = panels[:1]
    focused = snapshot.focused
    if focused < 0 or focused >= len(panels):
        focused = 0
    return DeckAreaState(
        panels=panels,
        focused=focused,
        layout=snapshot.layout,
        ratio=snapshot.ratio if snapshot.ratio in RATIO_STEPS else 50,
        nodes_collapsed=bool(snapshot.nodes_collapsed),
    )


def _serialize_agents_deck_state(snapshot: AgentsDeckStateSnapshot) -> str:
    decoded = {
        "schema_version": SCHEMA_VERSION,
        "layout": snapshot.layout.value,
        "ratio": snapshot.ratio,
        "focused": snapshot.focused,
        "nodes_collapsed": snapshot.nodes_collapsed,
        "panels": [
            {"deck": item.deck.value, "preferred_card": item.preferred_card}
            for item in snapshot.panels
        ],
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
    "SCHEMA_VERSION",
    "area_state_from_snapshot",
    "load_agents_deck_state",
    "save_agents_deck_state",
    "snapshot_from_area_state",
]
