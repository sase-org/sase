"""sase's TUI PNG visual snapshots for the read-only Agents Archive view.

Covers the archive-proof fixtures: day grouping with open and folded
banners, containers, interrupted rows with italic start-only time, the
archived identity header plus Reply, missing-content cards, the
empty/missing/rebuilding states, the parked tab marker, and the Archive
help box. Row dates are fixed around a pinned visual now so banners and
time chips are deterministic.

This module is a facade: the tests live in the ``*_archive_list``,
``*_archive_states``, and ``*_archive_actions`` modules with shared
fixtures in ``_ace_agents_archive_png_snapshot_shared``. The public
names are re-exported here so the original import path keeps working.
"""

from __future__ import annotations

import pytest

from tests.ace.tui.visual._ace_agents_archive_png_snapshot_shared import NOW
from tests.ace.tui.visual.test_ace_png_snapshots_agents_archive_actions import (
    test_archive_chooser_marked_png_snapshot,
    test_archive_chooser_png_snapshot,
    test_archive_marked_row_png_snapshot,
    test_archive_restored_overlay_png_snapshot,
    test_archive_restored_row_with_toast_png_snapshot,
)
from tests.ace.tui.visual.test_ace_png_snapshots_agents_archive_list import (
    test_archive_folded_banners_png_snapshot,
    test_archive_list_png_snapshot,
    test_archive_parked_marker_png_snapshot,
)
from tests.ace.tui.visual.test_ace_png_snapshots_agents_archive_states import (
    test_archive_empty_png_snapshot,
    test_archive_help_png_snapshot,
    test_archive_missing_content_png_snapshot,
    test_archive_missing_index_png_snapshot,
    test_archive_rebuilding_png_snapshot,
    test_archived_identity_reply_png_snapshot,
)

pytestmark = pytest.mark.visual

__test__ = False

__all__ = [
    "NOW",
    "test_archive_chooser_marked_png_snapshot",
    "test_archive_chooser_png_snapshot",
    "test_archive_empty_png_snapshot",
    "test_archive_folded_banners_png_snapshot",
    "test_archive_help_png_snapshot",
    "test_archive_list_png_snapshot",
    "test_archive_marked_row_png_snapshot",
    "test_archive_missing_content_png_snapshot",
    "test_archive_missing_index_png_snapshot",
    "test_archive_parked_marker_png_snapshot",
    "test_archive_rebuilding_png_snapshot",
    "test_archive_restored_overlay_png_snapshot",
    "test_archive_restored_row_with_toast_png_snapshot",
    "test_archived_identity_reply_png_snapshot",
]
