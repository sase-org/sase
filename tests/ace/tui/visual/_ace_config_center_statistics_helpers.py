"""Monkeypatch helpers for deterministic Statistics-tab PNG snapshots."""

from __future__ import annotations

import pytest

from sase.ace.tui.modals import statistics_pane as sp
from sase.ace.tui.modals import statistics_pane_footprint as spf
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
from tests.ace.tui._statistics_pane_helpers import _result


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
            facets={"code"}, project_filter=project_filter
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


def _snapshot_footprint_card(
    target: tuple[str, str],
    *,
    actor: str = "you",
    window_days: int | None = None,
    today: str = "",
) -> dict[str, object]:
    """Return a deterministic evidence card for the Statistics snapshots."""
    del actor, window_days, today
    report = _result("footprint", _STATISTICS_RANGE)
    rows = [dict(row) for row in report.footprint["rows"]]
    areas = [dict(area) for area in report.footprint["areas"]]
    kind, name = target
    if kind == "area":
        area = next((item for item in areas if item["area"] == name), None)
        if area is None:
            area = {
                "area": name,
                "total": 0,
                "used": 0,
                "used_pct": 0,
                "recency_7d": 0,
                "recency_30d": 0,
                "recency_window": 0,
                "recency_none": 0,
                "recency_not_measured": 0,
            }
        unused = [
            {
                "id": row["id"],
                "label": row["label"],
                "ns": row["ns"],
                "area": row["area"],
                "kind": row["kind"],
                "loc": row.get("loc"),
            }
            for row in rows
            if row["area"] == name and not row["days_used"]
        ]
        return {
            "row": {
                "id": name,
                "label": name,
                "ns": name.split(".", 1)[0] if "." in name else name,
                "area": name,
                "kind": "area",
                "state": "",
                "uses": {"human": 0, "agent": 0, "automation": 0},
                "days_used": 0,
                "last_used_day": None,
                "last_used_actor": None,
                "via": {},
                "loc": None,
                "protected": None,
                "decision": None,
                "decision_reason": None,
                "coverage_incomplete": False,
            },
            "daily_series": [],
            "first_in_catalog": None,
            "last_in_catalog": None,
            "parent": None,
            "children": [],
            "retire_with": [],
            "area_summary": {**area, "unused_by_loc": unused},
        }
    row = next((item for item in rows if item["id"] == name), rows[0])
    series = [
        {
            "day": f"2026-10-{day:02d}",
            "n": 1 if row["days_used"] and day % 3 else 0,
            "measured": bool(day % 2),
        }
        for day in range(1, 15)
    ]
    return {
        "row": dict(row),
        "daily_series": series,
        "first_in_catalog": "2026-08-01",
        "last_in_catalog": "2026-10-26",
        "parent": None,
        "children": [],
        "retire_with": [],
        "area_summary": None,
    }


def _patch_statistics_footprint(
    monkeypatch: pytest.MonkeyPatch,
    *,
    empty: bool = False,
    all_unknown: bool = False,
) -> None:
    """Return deterministic Footprint reports for the Statistics snapshots."""
    monkeypatch.setattr(sp, "resolve_preset", lambda _key: _STATISTICS_RANGE)
    monkeypatch.setattr(spf, "fetch_footprint_card", _snapshot_footprint_card)

    def load(
        view: str,
        selected_range: object,
        project_filter: str | None = None,
        macro_focus: str | None = None,
        perf_group_by: str = "subsystem",
        *,
        footprint_lens: str = "map",
        footprint_actor: str = "you",
        footprint_area: str | None = None,
        **_kw: object,
    ) -> StatisticsViewData:
        if view != "footprint":
            return _populated_statistics_view(
                view,
                selected_range,  # type: ignore[arg-type]
                project_filter,
                macro_focus,
                perf_group_by=perf_group_by,  # type: ignore[arg-type]
            )
        result = _result(
            "footprint",
            selected_range,  # type: ignore[arg-type]
            project_filter=project_filter,
            macro_focus=macro_focus,
            empty=empty,
            footprint_lens=footprint_lens,
            footprint_actor=footprint_actor,
            footprint_area=footprint_area,
        )
        if all_unknown and result.footprint is not None:
            result.footprint["tiles"] = {
                "total": 18,
                "used": 0,
                "candidates": 0,
                "candidates_preview": True,
                "rare_by_design": 0,
                "agent_only": 0,
                "not_measured": 18,
            }
            result.footprint["areas"] = [
                {
                    "area": "mobile",
                    "total": 18,
                    "used": 0,
                    "used_pct": 0,
                    "recency_7d": 0,
                    "recency_30d": 0,
                    "recency_window": 0,
                    "recency_none": 0,
                    "recency_not_measured": 18,
                }
            ]
        return result

    monkeypatch.setattr(sp, "load_statistics_view", load)


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
    "_patch_statistics_footprint",
    "_patch_statistics_loading",
    "_patch_statistics_perf_degraded",
    "_patch_statistics_populated",
    "_patch_statistics_projects_measuring_code",
]
