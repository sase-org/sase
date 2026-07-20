"""Shared AXE restart helpers for plugin CLI mutations."""

from __future__ import annotations

from sase.main.update_restart import restart_after_update
from sase.main.update_types import AxeRunningFn, RestartAxeFn, RestartInfo
from sase.uv_tool.runner import ChangeKind, UvChangeSet


def _change_set_changed(change_set: UvChangeSet) -> bool:
    """Whether a uv operation changed any installed package."""
    return any(change.kind is not ChangeKind.UNCHANGED for change in change_set.changes)


def restart_after_plugin_change(
    change_set: UvChangeSet,
    *,
    axe_running_fn: AxeRunningFn,
    restart_axe_fn: RestartAxeFn,
    source: str = "sase plugin change",
) -> RestartInfo:
    """Restart AXE when a plugin uv operation changed installed code."""
    return restart_after_update(
        changed=_change_set_changed(change_set),
        axe_running_fn=axe_running_fn,
        restart_axe_fn=restart_axe_fn,
        source=source,
    )


__all__ = ["restart_after_plugin_change"]
