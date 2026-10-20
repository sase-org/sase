"""sase's TUI PNG visual snapshots for Agents deck views.

Covers the view chip (effective layout plus lock) on Main and Files decks:
automatic page blocks, one ``P`` to locked page cards, two ``P`` to locked
spread, a narrow split with a focused lock versus an unfocused auto chip, a
forced Files spread, and a media-blocked Files spread request.

This module is a facade: the tests live in the ``*_deck_views_main`` and
``*_deck_views_files`` modules with shared fixtures in
``_ace_agents_deck_views_png_snapshot_shared``. The public names are
re-exported here so the original import path keeps working.
"""

from __future__ import annotations

import pytest

from tests.ace.tui.visual.test_ace_png_snapshots_agents_deck_views_files import (
    test_agents_deck_view_files_fixed_spread_png_snapshot,
    test_agents_deck_view_files_instruction_bundles_png_snapshot,
    test_agents_deck_view_files_media_blocked_png_snapshot,
)
from tests.ace.tui.visual.test_ace_png_snapshots_agents_deck_views_main import (
    test_agents_deck_view_auto_page_blocks_png_snapshot,
    test_agents_deck_view_fixed_page_cards_png_snapshot,
    test_agents_deck_view_fixed_spread_png_snapshot,
    test_agents_deck_view_one_card_png_snapshot,
    test_agents_deck_view_paged_bottom_cue_png_snapshot,
    test_agents_deck_view_split_narrow_png_snapshot,
    test_agents_deck_view_split_spread_paged_png_snapshot,
    test_agents_deck_view_spread_all_in_view_png_snapshot,
)

pytestmark = pytest.mark.visual

__test__ = False

__all__ = [
    "test_agents_deck_view_auto_page_blocks_png_snapshot",
    "test_agents_deck_view_files_fixed_spread_png_snapshot",
    "test_agents_deck_view_files_instruction_bundles_png_snapshot",
    "test_agents_deck_view_files_media_blocked_png_snapshot",
    "test_agents_deck_view_fixed_page_cards_png_snapshot",
    "test_agents_deck_view_fixed_spread_png_snapshot",
    "test_agents_deck_view_one_card_png_snapshot",
    "test_agents_deck_view_paged_bottom_cue_png_snapshot",
    "test_agents_deck_view_split_narrow_png_snapshot",
    "test_agents_deck_view_split_spread_paged_png_snapshot",
    "test_agents_deck_view_spread_all_in_view_png_snapshot",
]
