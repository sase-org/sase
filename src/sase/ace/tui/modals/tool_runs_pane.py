"""Admin Center Tools pane: Runs, Failures, and Catalog views (sase-1bt.10).

Read-only project/machine views over the machine-local ToolRun ledger.
Never reconciles, never settles, never shells out on a UI path. Stop and
run actions belong to phase ``tool-run-actions`` (sase-1bt.11).

This module is the stable public facade; shell lifecycle, loading,
rendering, key handling, and tool actions live in the focused
``tool_runs_pane_*`` sibling modules.
"""

from __future__ import annotations

from textual.containers import Vertical

from .tool_runs_pane_data import ToolRunFocusTarget
from .tool_runs_pane_events import ToolRunsPaneEventsMixin
from .tool_runs_pane_loading import ToolRunsPaneLoadingMixin
from .tool_runs_pane_render import ToolRunsPaneRenderMixin
from .tool_runs_pane_shell import ToolRunsPaneShellMixin
from .tool_runs_pane_tool_actions import ToolRunsPaneToolActionsMixin


class ToolRunsPane(
    ToolRunsPaneShellMixin,
    ToolRunsPaneLoadingMixin,
    ToolRunsPaneRenderMixin,
    ToolRunsPaneEventsMixin,
    ToolRunsPaneToolActionsMixin,
    Vertical,
):
    """Three read-only ToolRun views with a shared detail region."""

    can_focus = False
    BINDINGS = []


__all__ = ["ToolRunFocusTarget", "ToolRunsPane"]
