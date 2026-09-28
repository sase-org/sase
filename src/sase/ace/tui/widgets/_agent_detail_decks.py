"""Deck-mode compose and delegation for AgentDetail."""

from __future__ import annotations

from typing import Any

from ._agent_detail_deck_refresh import AgentDetailDeckRefreshMixin
from ._agent_detail_deck_show import AgentDetailDeckShowMixin
from ._agent_detail_deck_source import AgentDetailDeckSourceMixin
from .decks.main_document import EMPTY_MAIN_DOCUMENT, MainDeckDocument


class AgentDetailDeckMixin(
    AgentDetailDeckSourceMixin,
    AgentDetailDeckRefreshMixin,
    AgentDetailDeckShowMixin,
):
    """Mixin providing deck-mode Main sink, refresh and accessors."""

    _main_deck_document: MainDeckDocument = EMPTY_MAIN_DOCUMENT
    _current_agent: Any | None
    _current_tribe_identity: Any | None
    _tribe_document_complete: bool
    _current_attempt_number: int | None
    _attempt_view_mode: str
    _agent_detail_generation: int


__all__ = ["AgentDetailDeckMixin"]
