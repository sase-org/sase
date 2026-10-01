"""sase's TUI PNG visual snapshots for Agents-tab SASE context metadata.

This module is a facade: the tests live in the ``*_sase_context_beads``,
``*_sase_context_plans``, and ``*_sase_context_sessions`` modules. The
public names are re-exported here so the original import path keeps
working.
"""

from __future__ import annotations

import pytest

from tests.ace.tui.visual.test_ace_png_snapshots_agents_sase_context_beads import (
    test_agents_bead_closed_by_agent_narrow_png_snapshot,
    test_agents_bead_closed_by_agent_png_snapshot,
    test_agents_bead_created_by_agent_narrow_png_snapshot,
    test_agents_bead_created_by_agent_png_snapshot,
    test_agents_bead_note_preview_png_snapshot,
)
from tests.ace.tui.visual.test_ace_png_snapshots_agents_sase_context_plans import (
    test_agents_epic_phase_roadmap_png_snapshot,
    test_agents_phase_bead_context_png_snapshot,
    test_agents_sase_plan_metadata_png_snapshot,
)
from tests.ace.tui.visual.test_ace_png_snapshots_agents_sase_context_sessions import (
    test_agents_partially_streamed_context_lanes_png_snapshot,
    test_agents_phase_agent_session_bead_and_plan_context_png_snapshot,
    test_agents_task_bead_notes_png_snapshot,
)

pytestmark = pytest.mark.visual

__test__ = False

__all__ = [
    "test_agents_bead_closed_by_agent_narrow_png_snapshot",
    "test_agents_bead_closed_by_agent_png_snapshot",
    "test_agents_bead_created_by_agent_narrow_png_snapshot",
    "test_agents_bead_created_by_agent_png_snapshot",
    "test_agents_bead_note_preview_png_snapshot",
    "test_agents_epic_phase_roadmap_png_snapshot",
    "test_agents_partially_streamed_context_lanes_png_snapshot",
    "test_agents_phase_agent_session_bead_and_plan_context_png_snapshot",
    "test_agents_phase_bead_context_png_snapshot",
    "test_agents_sase_plan_metadata_png_snapshot",
    "test_agents_task_bead_notes_png_snapshot",
]
