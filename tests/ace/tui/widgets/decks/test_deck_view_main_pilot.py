"""Pilot Main deck-view policy tests: transitions keep the reader's place.

The test cases live in focused private modules. This module keeps their original
import and pytest collection path stable.
"""

from pathlib import Path as Path
from typing import Any as Any

import pytest as pytest
from rich.text import Text as Text
from textual.app import App as App, ComposeResult as ComposeResult
from textual.containers import VerticalScroll as VerticalScroll

from sase.ace.testing import wait_for as wait_for
from sase.ace.tui.agent_decks_settings import AgentDecksSettings as AgentDecksSettings
from sase.ace.tui.widgets.agent_detail import AgentDetail as AgentDetail
from sase.ace.tui.widgets.decks.card_block import (
    BlockMeta as BlockMeta,
    CardBlock as CardBlock,
)
from sase.ace.tui.widgets.decks.card_part import (
    CardPart as CardPart,
    context_card as context_card,
    reply_card as reply_card,
)
from sase.ace.tui.widgets.decks.main_document import (
    MainDeckDocument as MainDeckDocument,
)
from sase.ace.tui.widgets.decks.model import (
    DeckId as DeckId,
    DeckLayout as DeckLayout,
    DeckView as DeckView,
    RenderMode as RenderMode,
)
from tests.ace.tui.widgets.decks._deck_view_main_transitions_tests import (
    test_enter_page_blocks_shows_anchor_not_newest as test_enter_page_blocks_shows_anchor_not_newest,
    test_partial_documents_store_without_applying as test_partial_documents_store_without_applying,
    test_rapid_view_changes_end_on_first_anchor as test_rapid_view_changes_end_on_first_anchor,
    test_view_change_keeps_block_and_offset as test_view_change_keeps_block_and_offset,
    test_view_change_keeps_bottom_pin as test_view_change_keeps_bottom_pin,
    test_view_change_keeps_nonzero_offset as test_view_change_keeps_nonzero_offset,
)
from tests.ace.tui.widgets.decks._deck_view_main_policy_tests import (
    test_cycle_focused_deck_view_from_auto as test_cycle_focused_deck_view_from_auto,
    test_cycle_unavailable_for_tools_empty_partial_single as test_cycle_unavailable_for_tools_empty_partial_single,
    test_final_panel_shows_no_badge_and_no_cycle as test_final_panel_shows_no_badge_and_no_cycle,
    test_fixed_policy_survives_navigation as test_fixed_policy_survives_navigation,
    test_persisted_view_restores_after_restart as test_persisted_view_restores_after_restart,
    test_reset_to_auto_matches_fresh_decision as test_reset_to_auto_matches_fresh_decision,
    test_resize_block_refresh_keeps_preferred_main_card as test_resize_block_refresh_keeps_preferred_main_card,
    test_resize_under_fixed_policy_never_transitions as test_resize_under_fixed_policy_never_transitions,
    test_spread_title_cue_and_paged_tabs_flip as test_spread_title_cue_and_paged_tabs_flip,
    test_spread_to_paged_resize_keeps_preferred_main_card as test_spread_to_paged_resize_keeps_preferred_main_card,
)
