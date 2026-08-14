"""Interactive cross-repository commit timeline for the Artifacts tab.

This module is the stable public entry point for the commits widgets.  The
implementation lives in focused sibling modules so callers can continue to
import and patch the same names as before.
"""

from __future__ import annotations

from typing import Any

from sase.ace.tui.widgets.prompt_panel._agent_commits import load_commit_diff_text
from sase.ace.tui.widgets.prompt_panel._agent_display_state import CommitViewSpec
from sase.vcs_log import run_vcs_log
from sase.vcs_log.models import VcsLogResult

from .commits_pane import (
    CommitCollector,
    CommitDiffLoader,
    CommitsPane as _CommitsPane,
)
from .commits_timeline import CommitsTimeline


def _default_collector(**kwargs: Any) -> VcsLogResult:
    """Resolve the public collector seam when the proc runs."""
    return run_vcs_log(**kwargs)


def _default_diff_loader(spec: CommitViewSpec) -> str | None:
    """Resolve the public diff-loader seam when the proc runs."""
    return load_commit_diff_text(spec)


class CommitsPane(_CommitsPane):
    """Public commits pane with backwards-compatible dependency seams."""

    def __init__(
        self,
        *,
        collector: CommitCollector | None = None,
        diff_loader: CommitDiffLoader | None = None,
        **kwargs: Any,
    ) -> None:
        super().__init__(
            collector=collector or _default_collector,
            diff_loader=diff_loader or _default_diff_loader,
            **kwargs,
        )


__all__ = ["CommitsPane", "CommitsTimeline"]
