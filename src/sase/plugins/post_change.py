"""Shared post-mutation effects for plugin install, update, and uninstall.

Every real plugin change diffs the mounted-command set around the ``uv``
mutation and refreshes shell completion in a fresh child process when the
command set changed. The refresh is best-effort, like ``sase update``: a
failure never fails the mutation and is reported with a retry command
(``sase completion refresh``).

Callers capture the *before* snapshot ahead of the ``uv`` mutation and call
:func:`apply_post_change_effects` right after it (calling
:func:`importlib.invalidate_caches` first, as done here), before
``restart_after_plugin_change``. The required-plugins gate command and the
TUI batch/combined install workers get these effects through the shared
:mod:`sase.plugins.operations` executors, so their outputs stay byte-stable
apart from the additive effect fields.
"""

from __future__ import annotations

import importlib
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from sase.completion.install_models import (
    CompletionRefreshReport,
    RefreshShellOutcome,
)
from sase.completion.refresh_child import refresh_completions_in_child
from sase.plugin_commands.snapshot import (
    CommandChanges,
    CommandSnapshot,
    diff_command_snapshots,
    take_command_snapshot,
)
from sase.uv_tool.detect import NotUvToolInstall, UvToolInstall, probe_uv_tool_install

#: Called to refresh completions when the command set changed. Receives the
#: probed uv-tool install and returns its refresh report.
RefreshFn = Callable[[UvToolInstall], CompletionRefreshReport]

#: Called to probe the managed uv-tool install for the child refresh.
ProbeFn = Callable[[], UvToolInstall | NotUvToolInstall]

#: Called to capture the command snapshot; defaults to the live scan.
SnapshotFn = Callable[[], CommandSnapshot]


@dataclass(frozen=True)
class PluginChangeEffects:
    """Command diff and completion-refresh outcome for one plugin mutation."""

    command_changes: CommandChanges
    completion_refresh: CompletionRefreshReport

    def to_json(self) -> dict[str, Any]:
        """Return the additive ``command_changes``/``completion_refresh`` shape."""
        return {
            "command_changes": self.command_changes.to_json(),
            "completion_refresh": self.completion_refresh.to_json(),
        }


def empty_effects() -> PluginChangeEffects:
    """Return effects for a mutation that changed no command and refreshed nothing."""
    return PluginChangeEffects(
        command_changes=CommandChanges(),
        completion_refresh=CompletionRefreshReport(attempted=False, outcomes=()),
    )


def apply_post_change_effects(
    before: CommandSnapshot,
    *,
    probe_fn: ProbeFn = probe_uv_tool_install,
    snapshot_fn: SnapshotFn = take_command_snapshot,
    refresh_fn: RefreshFn | None = None,
) -> PluginChangeEffects:
    """Diff *before* against the live command set and refresh as needed.

    Takes the *after* snapshot (after invalidating import caches so in-process
    metadata reads observe the just-finished ``uv`` mutation), then refreshes
    completion in a fresh child process only when the command set changed. A
    refresh failure degrades to a failed report with a retry hint and never
    raises.
    """
    importlib.invalidate_caches()
    try:
        after = snapshot_fn()
    except Exception:  # noqa: BLE001 — diffs must never fail the mutation.
        after = before
    changes = diff_command_snapshots(before, after)
    if not changes:
        return PluginChangeEffects(
            command_changes=changes,
            completion_refresh=CompletionRefreshReport(attempted=False, outcomes=()),
        )
    return PluginChangeEffects(
        command_changes=changes,
        completion_refresh=_refresh_completion(probe_fn, refresh_fn),
    )


def _refresh_completion(
    probe_fn: ProbeFn, refresh_fn: RefreshFn | None
) -> CompletionRefreshReport:
    """Run the child completion refresh, degrading every failure to a report."""
    try:
        if refresh_fn is not None:
            install = probe_fn()
            if isinstance(install, NotUvToolInstall):
                return _skipped_refresh()
            return refresh_fn(install)
        install = probe_fn()
        if isinstance(install, NotUvToolInstall):
            return _skipped_refresh()
        return refresh_completions_in_child(install)
    except Exception as exc:  # noqa: BLE001 — refresh is best-effort.
        return _failed_refresh(f"completion refresh failed: {exc}")


def _skipped_refresh() -> CompletionRefreshReport:
    return CompletionRefreshReport(attempted=False, outcomes=())


def _failed_refresh(detail: str) -> CompletionRefreshReport:
    return CompletionRefreshReport(
        attempted=True,
        outcomes=(
            RefreshShellOutcome(
                shell="*",
                ok=False,
                detail=f"{detail} (retry: sase completion refresh)",
                target=None,
            ),
        ),
    )


__all__ = [
    "PluginChangeEffects",
    "apply_post_change_effects",
    "empty_effects",
]
