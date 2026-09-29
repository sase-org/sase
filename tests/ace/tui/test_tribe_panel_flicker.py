"""Tribe panel flicker regression coverage (plan 202609/tribe_panel_flicker).

Facade over the split modules. See
:mod:`tests.ace.tui.test_tribe_panel_flicker_debounced`,
:mod:`tests.ace.tui.test_tribe_panel_flicker_enrichment`, and
:mod:`tests.ace.tui.test_tribe_panel_flicker_display` for the implementations.
"""

from __future__ import annotations

from tests.ace.tui.test_tribe_panel_flicker_debounced import (
    test_different_tribe_still_gets_cheap_placeholder,
    test_fire_debounced_defers_while_prompt_input_active,
    test_refresh_tribe_summary_only_defers_while_prompt_input_active,
    test_same_tribe_refresh_skips_cheap_placeholder,
    test_shows_complete_tribe_document_lifecycle,
)
from tests.ace.tui.test_tribe_panel_flicker_display import (
    test_selected_tribe_noop_refresh_keeps_main_deck_stable,
    test_update_tribe_display_memo_skips_identical_rebuild,
    test_update_tribe_display_rebuilds_on_theme_change,
)
from tests.ace.tui.test_tribe_panel_flicker_enrichment import (
    test_departed_units_are_filtered_from_disk_sections,
    test_identical_enrichment_result_posts_no_message,
    test_signature_change_retains_disk_and_requests_refresh,
)

__all__ = [
    "test_departed_units_are_filtered_from_disk_sections",
    "test_different_tribe_still_gets_cheap_placeholder",
    "test_fire_debounced_defers_while_prompt_input_active",
    "test_identical_enrichment_result_posts_no_message",
    "test_refresh_tribe_summary_only_defers_while_prompt_input_active",
    "test_same_tribe_refresh_skips_cheap_placeholder",
    "test_selected_tribe_noop_refresh_keeps_main_deck_stable",
    "test_shows_complete_tribe_document_lifecycle",
    "test_signature_change_retains_disk_and_requests_refresh",
    "test_update_tribe_display_memo_skips_identical_rebuild",
    "test_update_tribe_display_rebuilds_on_theme_change",
]
