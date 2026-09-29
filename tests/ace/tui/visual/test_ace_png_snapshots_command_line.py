"""sase's TUI PNG visual snapshots for the ``:`` Command Line panel shell.

This module is a facade: the tests live in the ``*_command_line_blocks`` and
``*_command_line_completion`` modules with shared panel helpers in
``_ace_command_line_png_snapshot_shared``. The public names are re-exported
here so the original import path keeps working.
"""

from __future__ import annotations

import pytest

from tests.ace.tui.visual.test_ace_png_snapshots_command_line_blocks import (
    test_command_line_block_expanded_png_snapshot,
    test_command_line_block_selected_png_snapshot,
    test_command_line_declined_png_snapshot,
    test_command_line_denied_png_snapshot,
    test_command_line_earlier_divider_png_snapshot,
    test_command_line_empty_png_snapshot,
    test_command_line_error_png_snapshot,
    test_command_line_foreground_png_snapshot,
    test_command_line_help_png_snapshot,
    test_command_line_running_png_snapshot,
    test_command_line_submit_failed_png_snapshot,
    test_command_line_success_png_snapshot,
    test_command_line_typed_ghost_png_snapshot,
)
from tests.ace.tui.visual.test_ace_png_snapshots_command_line_completion import (
    test_command_line_completion_popup_png_snapshot,
    test_command_line_doc_peek_png_snapshot,
    test_command_line_empty_state_png_snapshot,
    test_command_line_history_search_png_snapshot,
    test_command_line_indexing_png_snapshot,
)

pytestmark = pytest.mark.visual

__all__ = [
    "test_command_line_block_expanded_png_snapshot",
    "test_command_line_block_selected_png_snapshot",
    "test_command_line_completion_popup_png_snapshot",
    "test_command_line_declined_png_snapshot",
    "test_command_line_denied_png_snapshot",
    "test_command_line_doc_peek_png_snapshot",
    "test_command_line_earlier_divider_png_snapshot",
    "test_command_line_empty_png_snapshot",
    "test_command_line_empty_state_png_snapshot",
    "test_command_line_error_png_snapshot",
    "test_command_line_foreground_png_snapshot",
    "test_command_line_help_png_snapshot",
    "test_command_line_history_search_png_snapshot",
    "test_command_line_indexing_png_snapshot",
    "test_command_line_running_png_snapshot",
    "test_command_line_submit_failed_png_snapshot",
    "test_command_line_success_png_snapshot",
    "test_command_line_typed_ghost_png_snapshot",
]
