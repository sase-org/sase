"""Shared entry point for ACE PNG visual snapshot helpers.

Implementations are grouped by responsibility in the sibling helper modules.
The underscore prefix keeps pytest from collecting this module.
"""

from __future__ import annotations

from tests.ace.tui.visual._ace_png_snapshot_fixtures import (
    agents as agents,
    agents_with_stopped_status as agents_with_stopped_status,
    axe_collected_data as axe_collected_data,
    changespecs as changespecs,
    hood_neighbor_agents as hood_neighbor_agents,
    project_records as project_records,
    retry_agent as retry_agent,
    visual_agents as visual_agents,
)
from tests.ace.tui.visual._ace_png_snapshot_startup import (
    patch_startup_loaders as patch_startup_loaders,
    wait_for_startup as wait_for_startup,
)
from tests.ace.tui.visual._ace_png_snapshot_waits import (
    _pending_visual_work as _pending_visual_work,
    assert_visual_frame_converged as assert_visual_frame_converged,
    wait_for_state as wait_for_state,
    wait_for_svg_contains as wait_for_svg_contains,
    wait_for_visual_idle as wait_for_visual_idle,
)

__all__ = [
    "_pending_visual_work",
    "assert_visual_frame_converged",
    "agents",
    "agents_with_stopped_status",
    "axe_collected_data",
    "changespecs",
    "hood_neighbor_agents",
    "patch_startup_loaders",
    "project_records",
    "retry_agent",
    "visual_agents",
    "wait_for_startup",
    "wait_for_state",
    "wait_for_svg_contains",
    "wait_for_visual_idle",
]
