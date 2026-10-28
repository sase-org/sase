"""Public facade for shared Statistics pane test helpers.

The implementations live in focused private modules; this module keeps their
public import path stable for tests.
"""

from tests.ace.tui._statistics_pane_payloads import NOW, activity_payload, run_payload
from tests.ace.tui._statistics_pane_results import result
from tests.ace.tui._statistics_pane_ui_helpers import (
    assert_range_scope_matches_selection,
    assert_statistics_chrome,
    open_statistics,
    patch_center,
    rail_text,
    rail_widget,
    render_plain,
    scope_plain,
    wait_statistics_settled,
)

__all__ = [
    "NOW",
    "activity_payload",
    "assert_range_scope_matches_selection",
    "assert_statistics_chrome",
    "open_statistics",
    "patch_center",
    "rail_text",
    "rail_widget",
    "render_plain",
    "result",
    "run_payload",
    "scope_plain",
    "wait_statistics_settled",
]
