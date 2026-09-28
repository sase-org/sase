"""CLI entry and timing helpers for ``sase bead work``."""

from __future__ import annotations

import argparse
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from sase.agent.launch_timing import LaunchTimingRecorder


BEAD_WORK_TIMING_ENV = "SASE_BEAD_WORK_TIMING"


def make_bead_work_timer(
    target: str,
    *,
    dry_run: bool,
    target_index: int | None = None,
    target_count: int | None = None,
    correlation_id: str | None = None,
) -> Any:
    """Build a launch timer promoted to info logs by ``SASE_BEAD_WORK_TIMING``."""
    from sase.agent.launch_timing import LaunchTimingRecorder
    from sase.bead.cli_work_from_plan_helpers import is_plan_file_target

    identity_field = "plan_path" if is_plan_file_target(target) else "bead_id"

    fields: dict[str, Any] = {identity_field: target, "dry_run": dry_run}
    if target_index is not None:
        fields["target_index"] = target_index
    if target_count is not None:
        fields["target_count"] = target_count
    if correlation_id is not None:
        fields["correlation_id"] = correlation_id

    return LaunchTimingRecorder(
        "bead_work",
        fields,
        info_env_vars=(BEAD_WORK_TIMING_ENV,),
        durable=True,
    )


def handle_bead_work(args: argparse.Namespace) -> None:
    """Dispatch CLI work while preserving the original public entry point."""
    from sase.bead.cli_work_entry import handle_bead_work as dispatch_bead_work

    dispatch_bead_work(args, timer_factory=make_bead_work_timer)


def preload_launch_imports(timer: LaunchTimingRecorder) -> None:
    """Eagerly import the deferred launch chain once code-swap lock is held."""
    if getattr(timer, "_sase_preloaded_launch_imports", False):
        return
    timer._sase_preloaded_launch_imports = True  # type: ignore[attr-defined]
    with timer.stage("preload_launch_imports"):
        import sase.ace.tui.actions.agent_workflow._ref_resolution  # noqa: F401
        import sase.agent.launcher  # noqa: F401


__all__ = [
    "BEAD_WORK_TIMING_ENV",
    "handle_bead_work",
    "make_bead_work_timer",
    "preload_launch_imports",
]
