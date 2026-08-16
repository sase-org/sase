"""Monkeypatch helpers for deterministic Statistics-tab PNG snapshots."""

from __future__ import annotations

import pytest

from sase.ace.tui.modals import statistics_pane as sp
from sase.ace.tui.modals.statistics_pane import StatisticsPane
from sase.ace.tui.modals.statistics_pane_data import StatisticsViewData
from sase.stats.views import build_statistics_views
from tests.ace.tui.visual._ace_config_center_statistics_fixtures import (
    _STATISTICS_NOW,
    _STATISTICS_RANGE,
)
from tests.ace.tui.visual._ace_config_center_statistics_views import (
    _degraded_perf_statistics_view,
    _populated_statistics_view,
)


def _patch_statistics_perf_degraded(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(sp, "resolve_preset", lambda _key: _STATISTICS_RANGE)
    monkeypatch.setattr(
        sp,
        "load_statistics_view",
        lambda view, selected_range, project_filter=None, xprompt_focus=None, perf_group_by="subsystem", **_kw: (
            _degraded_perf_statistics_view(
                view,
                selected_range,
                project_filter,
                xprompt_focus,
                perf_group_by=perf_group_by,
            )
        ),
    )


def _patch_statistics_populated(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(sp, "resolve_preset", lambda _key: _STATISTICS_RANGE)
    monkeypatch.setattr(
        sp,
        "load_statistics_view",
        lambda view, selected_range, project_filter=None, xprompt_focus=None, perf_group_by="subsystem", **_kw: (
            _populated_statistics_view(
                view,
                selected_range,
                project_filter,
                xprompt_focus,
                perf_group_by=perf_group_by,
            )
        ),
    )


def _patch_statistics_empty(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(sp, "resolve_preset", lambda _key: _STATISTICS_RANGE)
    monkeypatch.setattr(
        sp,
        "load_statistics_view",
        lambda view, selected_range, project_filter=None, xprompt_focus=None, **_kw: (
            StatisticsViewData(
                view=view,
                selected_range=selected_range,
                generated_at=_STATISTICS_NOW,
                views=build_statistics_views({}, {}),
                project_filter=project_filter,
                xprompt_focus=xprompt_focus,
            )
        ),
    )


def _patch_statistics_loading(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(sp, "resolve_preset", lambda _key: _STATISTICS_RANGE)

    def stay_loading(self: StatisticsPane) -> None:
        self._loading = True
        self._update_heading()
        self._paint_loading()

    monkeypatch.setattr(StatisticsPane, "_start_load", stay_loading)


__all__ = [
    "_patch_statistics_empty",
    "_patch_statistics_loading",
    "_patch_statistics_perf_degraded",
    "_patch_statistics_populated",
]
