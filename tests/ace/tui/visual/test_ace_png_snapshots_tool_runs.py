"""ACE PNG snapshots for ToolRun TUI surfaces (epic sase-1bt, cutover).

Every surface reads deterministic fixtures through one loader seam each
for glance, node summaries, and run detail, with pinned clocks and no
SQLite. Generation is not approval: inspect every new PNG.

This module is a facade: the tests live in the ``*_rows``,
``*_header``, ``*_cards``, ``*_session``, ``*_admin``, and
``*_overlays`` modules with shared fixtures in
``_ace_tool_runs_png_snapshot_shared``. The public names are re-exported
here so the original import path keeps working.
"""

from __future__ import annotations

import pytest

from tests.ace.tui.visual.test_ace_png_snapshots_tool_runs_admin import (
    test_tool_runs_admin_pane_png_snapshots,
)
from tests.ace.tui.visual.test_ace_png_snapshots_tool_runs_cards import (
    test_tool_runs_card_png_snapshots,
)
from tests.ace.tui.visual.test_ace_png_snapshots_tool_runs_header import (
    test_tool_runs_header_chips_png_snapshots,
)
from tests.ace.tui.visual.test_ace_png_snapshots_tool_runs_overlays import (
    test_tool_runs_notification_png_snapshot,
    test_tool_runs_procs_marker_png_snapshot,
)
from tests.ace.tui.visual.test_ace_png_snapshots_tool_runs_rows import (
    test_tool_runs_rows_png_snapshots,
)
from tests.ace.tui.visual.test_ace_png_snapshots_tool_runs_session import (
    test_tool_runs_session_rail_png_snapshot,
)

pytestmark = pytest.mark.visual

__test__ = False

__all__ = [
    "test_tool_runs_admin_pane_png_snapshots",
    "test_tool_runs_card_png_snapshots",
    "test_tool_runs_header_chips_png_snapshots",
    "test_tool_runs_notification_png_snapshot",
    "test_tool_runs_procs_marker_png_snapshot",
    "test_tool_runs_rows_png_snapshots",
    "test_tool_runs_session_rail_png_snapshot",
]
