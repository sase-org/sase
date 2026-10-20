"""Pilot tests for deck split layouts, focus and ratio.

The test cases live in focused private modules. This module keeps their original
import and pytest collection path stable.
"""

from pathlib import Path as Path

import pytest as pytest
from textual.app import App as App, ComposeResult as ComposeResult
from textual.binding import Binding as Binding

from sase.ace.tui.actions.agents._deck_layout_actions import (
    AgentDeckLayoutActionsMixin as AgentDeckLayoutActionsMixin,
)
from sase.ace.tui.bindings import DEFAULT_BINDINGS as DEFAULT_BINDINGS
from sase.ace.tui.widgets.agent_detail import AgentDetail as AgentDetail
from sase.ace.tui.widgets.decks.model import DeckId as DeckId, DeckLayout as DeckLayout
from tests.ace.tui.widgets.decks._deck_split_test_support import (
    make_agent as make_agent,
    make_artifact_agent as make_artifact_agent,
    pin_paged as pin_paged,
)
from tests.ace.tui.widgets.decks._deck_split_layout_tests import (
    test_backslash_opens_top_bottom_and_keeps_focus as test_backslash_opens_top_bottom_and_keeps_focus,
    test_pipe_opens_left_right_and_unsplit_keeps_focused as test_pipe_opens_left_right_and_unsplit_keeps_focused,
    test_unsplit_keeps_first_when_first_focused as test_unsplit_keeps_first_when_first_focused,
    test_structural_keys_never_remount_survivors as test_structural_keys_never_remount_survivors,
    test_turn_keeps_widget_identities as test_turn_keeps_widget_identities,
    test_ctrl_f_flips_focus_and_single_noop as test_ctrl_f_flips_focus_and_single_noop,
    test_ratio_steps_and_clamp as test_ratio_steps_and_clamp,
)
from tests.ace.tui.widgets.decks._deck_split_content_tests import (
    test_context_reply_for_agent_without_files_or_tools as test_context_reply_for_agent_without_files_or_tools,
    test_main_document_fans_out_to_both as test_main_document_fans_out_to_both,
    test_ctrl_n_p_act_on_focused_panel as test_ctrl_n_p_act_on_focused_panel,
    test_duplicate_files_single_fetch as test_duplicate_files_single_fetch,
    test_duplicate_tools_single_fetch as test_duplicate_tools_single_fetch,
)
from tests.ace.tui.widgets.decks._deck_split_three_panel_tests import (
    test_three_panel_resize_clamps_to_minimums as test_three_panel_resize_clamps_to_minimums,
    test_close_each_of_three_panels_keeps_textual_focus as test_close_each_of_three_panels_keeps_textual_focus,
)
from tests.ace.tui.widgets.decks._deck_split_key_tests import (
    test_real_deck_keys_reach_actions_on_two_and_three_panels as test_real_deck_keys_reach_actions_on_two_and_three_panels,
    test_real_split_keys_keep_focus_on_original_widget as test_real_split_keys_keep_focus_on_original_widget,
    test_deck_swap_keeps_identity_and_click_focuses_after_swap as test_deck_swap_keeps_identity_and_click_focuses_after_swap,
    test_deck_close_each_and_erase_through_keys as test_deck_close_each_and_erase_through_keys,
    test_deck_erase_through_keys_with_main_and_pair_focused as test_deck_erase_through_keys_with_main_and_pair_focused,
    test_deck_rapid_keys_leave_valid_state as test_deck_rapid_keys_leave_valid_state,
    test_tab_disjoint_availability_for_swap_and_turn as test_tab_disjoint_availability_for_swap_and_turn,
)
