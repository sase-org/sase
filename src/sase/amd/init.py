"""Compatibility facade for ``sase amd init`` planning and application."""

from __future__ import annotations

from pathlib import Path

import sase.config.core as config_core

from . import _planner
from ._memory import plan_amd_memory_sync
from ._planner import plan_amd_init
from ._runner import run_amd_init
from ._shared import AmdInitPlan, AmdMemorySyncPlan


def _build_amd_init_plan(
    root: Path | None = None, *, explicit: bool = True
) -> AmdInitPlan:
    """Compatibility wrapper for tests that imported the former private helper."""
    return _planner.build_amd_init_plan(root, explicit=explicit)


__all__ = [
    "AmdMemorySyncPlan",
    "_build_amd_init_plan",
    "config_core",
    "plan_amd_memory_sync",
    "plan_amd_init",
    "run_amd_init",
]
