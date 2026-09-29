"""sase's TUI PNG visual snapshots for the ⊛ FINAL deck (epic sase-1b2, bead sase-1b2.19).

Deterministic goldens for every glance and deck state, built on fixed
fixtures: row states (FINALIZING, ``⊛✗``, ``⊛⏸``, ``⊛!``, success
silence), Reply receipts (running, failed with reason, deferred plus
not-triggered), the FINAL deck (single successful commit with
declaration rejections, failed check across two attempts, a plugin
instance, an Overview with an unselected instance and drift, a session
container with run blocks and the rail), the Reply/FINAL split, the
deck picker with ``n``, and the narrow title tiers.

This module is a facade: the tests live in the ``*_final_rows``,
``*_final_receipts``, ``*_final_decks``, and ``*_final_session`` modules
with shared fixtures in ``_ace_agents_final_png_snapshot_shared``. The
public names are re-exported here so the original import path keeps
working.
"""

from __future__ import annotations

import pytest

from tests.ace.tui.visual.test_ace_png_snapshots_agents_final_decks import (
    test_agents_final_failed_check_png_snapshot,
    test_agents_final_overview_unselected_png_snapshot,
    test_agents_final_plugin_png_snapshot,
    test_agents_final_single_commit_png_snapshot,
)
from tests.ace.tui.visual.test_ace_png_snapshots_agents_final_receipts import (
    test_agents_final_receipt_deferred_png_snapshot,
    test_agents_final_receipt_failed_png_snapshot,
    test_agents_final_receipt_running_png_snapshot,
)
from tests.ace.tui.visual.test_ace_png_snapshots_agents_final_rows import (
    test_agents_final_row_states_png_snapshot,
)
from tests.ace.tui.visual.test_ace_png_snapshots_agents_final_session import (
    test_agents_final_narrow_tiers_png_snapshot,
    test_agents_final_picker_png_snapshot,
    test_agents_final_reply_split_png_snapshot,
    test_agents_final_session_blocks_png_snapshot,
)

pytestmark = pytest.mark.visual

__all__ = [
    "test_agents_final_failed_check_png_snapshot",
    "test_agents_final_narrow_tiers_png_snapshot",
    "test_agents_final_overview_unselected_png_snapshot",
    "test_agents_final_picker_png_snapshot",
    "test_agents_final_plugin_png_snapshot",
    "test_agents_final_receipt_deferred_png_snapshot",
    "test_agents_final_receipt_failed_png_snapshot",
    "test_agents_final_receipt_running_png_snapshot",
    "test_agents_final_reply_split_png_snapshot",
    "test_agents_final_row_states_png_snapshot",
    "test_agents_final_session_blocks_png_snapshot",
    "test_agents_final_single_commit_png_snapshot",
]
