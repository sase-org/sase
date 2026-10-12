"""Plan modal rendering: rail layout, tinted first frame, keypress cost, and polling.

Split facade: the tests now live in ``test_plan_decision_ace_render_rail``,
``test_plan_decision_ace_render_cards``, and
``test_plan_decision_ace_render_state``. This module re-exports the public
names so the original import path keeps working. It collects no tests itself.
"""

from __future__ import annotations

from tests.ace.tui.test_plan_decision_ace_render_cards import (
    test_decision_cards_never_clip_with_stylesheet,
    test_decision_density_pins_other_rows_and_caps_current_card,
)
from tests.ace.tui.test_plan_decision_ace_render_rail import (
    test_compact_verdict_stays_inside_rail_with_stylesheet,
    test_decision_rail_widths_and_narrow_dock,
    test_generic_gate_rail_stays_42_with_stylesheet,
)
from tests.ace.tui.test_plan_decision_ace_render_state import (
    test_draft_edit_avoids_revalidate_relex,
    test_first_frame_tint_keeps_syntax,
    test_one_keypress_computes_sheet_once_and_refreshes_edited_card,
    test_plan_actions_use_compact_caption_and_other_gates_keep_descriptions,
    test_settled_polling_reads_only_open_modal,
)

__test__ = False

__all__ = [
    "test_compact_verdict_stays_inside_rail_with_stylesheet",
    "test_decision_cards_never_clip_with_stylesheet",
    "test_decision_density_pins_other_rows_and_caps_current_card",
    "test_decision_rail_widths_and_narrow_dock",
    "test_draft_edit_avoids_revalidate_relex",
    "test_first_frame_tint_keeps_syntax",
    "test_generic_gate_rail_stays_42_with_stylesheet",
    "test_one_keypress_computes_sheet_once_and_refreshes_edited_card",
    "test_plan_actions_use_compact_caption_and_other_gates_keep_descriptions",
    "test_settled_polling_reads_only_open_modal",
]
