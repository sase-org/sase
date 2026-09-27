"""Feature-flag helper package for the ⊛ FINAL deck beta (epic sase-1b2)."""

from sase.ace.tui.widgets.decks.final.document import (
    FINAL_OVERVIEW_CARD_ID,
    FINAL_OVERVIEW_TITLE,
    build_final_deck_document,
    decide_final_mode,
    final_default_card,
    final_instance_card_id,
    final_instance_tab_title,
)
from sase.ace.tui.widgets.decks.final.flag import final_deck_enabled
from sase.ace.tui.widgets.decks.final.loader import (
    FinalDeckLoadResult,
    cached_final_result,
    clear_final_cache,
    final_cache_key,
    load_final_deck,
    project_node_view,
    store_final_result,
)
from sase.ace.tui.widgets.decks.final.view import FinalDeckLoaded, FinalDeckView

__all__ = [
    "FINAL_OVERVIEW_CARD_ID",
    "FINAL_OVERVIEW_TITLE",
    "FinalDeckLoadResult",
    "FinalDeckLoaded",
    "FinalDeckView",
    "build_final_deck_document",
    "cached_final_result",
    "clear_final_cache",
    "decide_final_mode",
    "final_cache_key",
    "final_deck_enabled",
    "final_default_card",
    "final_instance_card_id",
    "final_instance_tab_title",
    "load_final_deck",
    "project_node_view",
    "store_final_result",
]
