"""Compatibility exports for AXE PNG snapshot fixtures.

Fixture implementations live in focused builder, report, run-state, and tree modules.
"""

from tests.ace.tui.visual._ace_axe_png_snapshot_builders import (
    make_chop_run,
    make_lumberjack_status,
)
from tests.ace.tui.visual._ace_axe_png_snapshot_report_fixtures import (
    axe_chop_report_absent_120x40,
    axe_chop_report_error_120x40,
    axe_chop_report_narrow_70x36,
    axe_chop_report_rich_120x40,
)
from tests.ace.tui.visual._ace_axe_png_snapshot_run_fixtures import (
    axe_chop_overrun_data,
    axe_lumberjack_error_data,
    axe_running_chop_data,
)
from tests.ace.tui.visual._ace_axe_png_snapshot_tree_fixtures import (
    axe_bgcmd_data,
    axe_description_overflow_data,
    axe_disabled_chop_data,
    axe_long_label_data,
    axe_lumberjack_tree_data,
)

__all__ = [
    "axe_bgcmd_data",
    "axe_chop_overrun_data",
    "axe_chop_report_absent_120x40",
    "axe_chop_report_error_120x40",
    "axe_chop_report_narrow_70x36",
    "axe_chop_report_rich_120x40",
    "axe_description_overflow_data",
    "axe_disabled_chop_data",
    "axe_long_label_data",
    "axe_lumberjack_error_data",
    "axe_lumberjack_tree_data",
    "axe_running_chop_data",
    "make_chop_run",
    "make_lumberjack_status",
]
