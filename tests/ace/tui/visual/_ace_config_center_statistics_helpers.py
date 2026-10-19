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
    _populated_project_stats,
    _populated_statistics_view,
)


def _patch_statistics_perf_degraded(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(sp, "resolve_preset", lambda _key: _STATISTICS_RANGE)
    monkeypatch.setattr(
        sp,
        "load_statistics_view",
        lambda view, selected_range, project_filter=None, macro_focus=None, perf_group_by="subsystem", **_kw: (
            _degraded_perf_statistics_view(
                view,
                selected_range,
                project_filter,
                macro_focus,
                perf_group_by=perf_group_by,
            )
        ),
    )


def _patch_statistics_populated(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(sp, "resolve_preset", lambda _key: _STATISTICS_RANGE)
    monkeypatch.setattr(
        sp,
        "load_statistics_view",
        lambda view, selected_range, project_filter=None, macro_focus=None, perf_group_by="subsystem", **_kw: (
            _populated_statistics_view(
                view,
                selected_range,
                project_filter,
                macro_focus,
                perf_group_by=perf_group_by,
            )
        ),
    )
    monkeypatch.setattr(
        sp,
        "_load_project_code_stats",
        lambda selected_range, project_filter=None, **_kw: _populated_project_stats(
            facets={"code"}
        ),
    )


def _patch_statistics_projects_measuring_code(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Paint Output/Runs while Code stays pending for a snapshot.

    A blocked Code worker never lets ``wait_for_visual_idle`` converge, so
    this fixture skips starting that worker (the loading-snapshot pattern)
    while leaving ``_code_complete`` false so the card shows
    ``measuring code…``.
    """
    monkeypatch.setattr(sp, "resolve_preset", lambda _key: _STATISTICS_RANGE)

    def load(
        view: str,
        selected_range: object,
        project_filter: str | None = None,
        macro_focus: str | None = None,
        perf_group_by: str = "subsystem",
        **_kw: object,
    ) -> StatisticsViewData:
        if view == "projects":
            return StatisticsViewData(
                view="projects",  # type: ignore[arg-type]
                selected_range=selected_range,  # type: ignore[arg-type]
                generated_at=_STATISTICS_NOW,
                views=None,
                project_filter=project_filter,
                macro_focus=macro_focus,
                project_stats=_populated_project_stats(facets={"output", "runs"}),
            )
        return _populated_statistics_view(
            view,
            selected_range,  # type: ignore[arg-type]
            project_filter,
            macro_focus,
            perf_group_by=perf_group_by,  # type: ignore[arg-type]
        )

    def load_code(
        selected_range: object,
        project_filter: str | None = None,
        **_kw: object,
    ) -> object:
        del selected_range, project_filter, _kw
        raise AssertionError("measuring-code snapshot must not start the Code worker")

    monkeypatch.setattr(sp, "load_statistics_view", load)
    monkeypatch.setattr(sp, "_load_project_code_stats", load_code)
    monkeypatch.setattr(
        StatisticsPane, "_start_code_load", lambda _self, _generation: None
    )


def _patch_statistics_empty(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(sp, "resolve_preset", lambda _key: _STATISTICS_RANGE)
    monkeypatch.setattr(
        sp,
        "load_statistics_view",
        lambda view, selected_range, project_filter=None, macro_focus=None, **_kw: (
            StatisticsViewData(
                view=view,
                selected_range=selected_range,
                generated_at=_STATISTICS_NOW,
                views=build_statistics_views({}, {}),
                project_filter=project_filter,
                macro_focus=macro_focus,
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
    "_patch_statistics_projects_measuring_code",
]
