"""Main-document sink keeps the deck subtitle counts in sync."""

from __future__ import annotations

from typing import Any

from rich.text import Text

from sase.ace.tui.widgets._agent_detail_deck_source import (
    AgentDetailDeckSourceMixin,
)
from sase.ace.tui.widgets.decks.card_part import CardPart
from sase.ace.tui.widgets.decks.main_document import EMPTY_MAIN_DOCUMENT


class _StubArea:
    """Deck area with no MAIN panels, so the sink only stores."""

    def panels_showing(self, _deck: object) -> tuple[()]:
        return ()


class _StubPanel:
    """Prompt panel whose sync render never fires the Main sink (deduped)."""

    def __init__(self) -> None:
        self.updated_agents: list[object] = []
        self._last_prompt_panel_content: Any = None
        self._last_prompt_panel_digest: Any = None
        self._main_document_partial = False
        self.on_update_display: Any = None

    def update_display(self, agent: object) -> None:
        self.updated_agents.append(agent)
        if self.on_update_display is not None:
            self.on_update_display(agent)


class _StubDetail(AgentDetailDeckSourceMixin):
    """Bare sink host recording availability refreshes."""

    def __init__(self) -> None:
        self._main_deck_document = EMPTY_MAIN_DOCUMENT
        self.availability_refreshes = 0
        self._current_agent: Any = None
        self._current_tribe_identity: Any = None
        self._attempt_view_mode = ""
        self._agent_detail_generation = 0
        self._identity: Any = ("agent", "stub", None)
        self._panel = _StubPanel()

    @property
    def metadata_identity(self) -> Any:
        return self._identity

    @property
    def deck_area(self) -> Any:
        return _StubArea()

    def _deck_refresh_availability(self) -> None:
        self.availability_refreshes += 1

    def _deck_source_panel(self) -> Any:
        return self._panel

    def _should_render_workflow_detail_async(
        self, agent: object, attempt_number: Any
    ) -> bool:
        del agent, attempt_number
        return False

    def _is_agent_detail_render_current(self, *args: Any) -> bool:
        del args
        return True


def _context_part() -> CardPart:
    return CardPart("context", "Context", Text("No prompt file found."))


def test_sink_refreshes_availability_when_cards_arrive() -> None:
    """A delivered Context card re-syncs availability (sase-1a3)."""
    detail = _StubDetail()
    detail._on_main_document(_context_part(), False, None)
    assert detail._main_deck_document.card_ids == ("context",)
    assert detail.availability_refreshes == 1


def test_sink_skips_availability_refresh_when_cards_unchanged() -> None:
    """Streaming block content without new cards does not re-sync."""
    detail = _StubDetail()
    detail._on_main_document(_context_part(), False, None)
    detail._on_main_document(_context_part(), True, None)
    assert detail.availability_refreshes == 1


def test_sink_refreshes_availability_when_cards_clear() -> None:
    """Clearing the document re-syncs availability back to empty."""
    detail = _StubDetail()
    detail._on_main_document(_context_part(), False, None)
    detail._on_main_document("", False, None)
    assert detail._main_deck_document.card_ids == ()
    assert detail.availability_refreshes == 2


def test_update_main_source_repushes_sink_when_render_deduped() -> None:
    """A digest-identical placeholder still delivers the new subject (sase-1kl.2).

    The re-sync only stores: the display path's own trailing availability
    refresh covers the subtitle, so no eager refresh fires here.
    """
    detail = _StubDetail()
    detail._current_agent = object()
    detail._panel._last_prompt_panel_content = _context_part()  # noqa: SLF001
    detail._update_main_source(object(), None)
    assert detail._main_deck_document.card_ids == ("context",)
    assert detail.availability_refreshes == 0


def test_sync_delivery_skips_eager_refresh() -> None:
    """A sync-render delivery leaves the trailing refresh to the display path."""
    detail = _StubDetail()
    detail._current_agent = object()
    detail._panel.on_update_display = (  # noqa: SLF001
        lambda _agent: detail._on_main_document(_context_part(), False, None)
    )
    detail._update_main_source(object(), None)
    assert detail._main_deck_document.card_ids == ("context",)
    assert detail.availability_refreshes == 0


def test_async_delivery_still_refreshes_eagerly() -> None:
    """A delivery outside the sync display still re-syncs (sase-1a3)."""
    detail = _StubDetail()
    detail._current_agent = object()
    detail._on_main_document(_context_part(), False, None)
    assert detail._main_deck_document.card_ids == ("context",)
    assert detail.availability_refreshes == 1


def test_update_main_source_skips_repush_when_subject_current() -> None:
    """A fresh same-subject delivery is not pushed twice."""
    detail = _StubDetail()
    detail._current_agent = object()
    detail._on_main_document(_context_part(), False, None)
    detail.availability_refreshes = 0
    detail._update_main_source(object(), None)
    assert detail._main_deck_document.card_ids == ("context",)
    assert detail.availability_refreshes == 0


def test_update_main_source_skips_repush_for_tribe_view() -> None:
    """Tribe summaries keep their established refresh route."""
    detail = _StubDetail()
    detail._current_agent = object()
    detail._current_tribe_identity = ("tribe", "stub")
    detail._panel._last_prompt_panel_content = _context_part()  # noqa: SLF001
    detail._update_main_source(object(), None)
    assert detail._main_deck_document.card_ids == ()
    assert detail.availability_refreshes == 0
