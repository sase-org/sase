"""Shared scheduler restart helpers for plugin CLI mutations."""

from __future__ import annotations

from sase.main.update_restart import restart_after_update
from sase.main.update_types import (
    RestartInfo,
    RestartSchedulerFn,
    SchedulerRunningFn,
)
from sase.uv_tool.runner import ChangeKind, UvChangeSet


def _change_set_changed(change_set: UvChangeSet) -> bool:
    """Whether a uv operation changed any installed package."""
    return any(change.kind is not ChangeKind.UNCHANGED for change in change_set.changes)


def restart_after_plugin_change(
    change_set: UvChangeSet,
    *,
    scheduler_running_fn: SchedulerRunningFn,
    restart_scheduler_fn: RestartSchedulerFn,
    source: str = "sase plugin change",
) -> RestartInfo:
    """Restart the scheduler when a plugin uv operation changed installed code."""
    return restart_after_update(
        changed=_change_set_changed(change_set),
        scheduler_running_fn=scheduler_running_fn,
        restart_scheduler_fn=restart_scheduler_fn,
        source=source,
    )


__all__ = ["restart_after_plugin_change"]
