"""Worker, interaction, and binding coverage for the Statistics tab."""

from __future__ import annotations

import asyncio
from pathlib import Path
from types import SimpleNamespace

import pytest
from rich.console import Console
from textual.widgets import Input, Static
from textual.worker import WorkerState

from sase.ace.testing import AcePage
from sase.ace.tui.keymaps import load_keymap_registry, statistics_help_bindings
from sase.ace.tui.modals import statistics_pane as sp
from sase.ace.tui.modals.config_center_modal import ConfigCenterModal
from sase.ace.tui.modals.statistics_pane import StatisticsPane
from sase.ace.tui.modals.statistics_help_modal import StatisticsHelpModal
from sase.ace.tui.modals.statistics_pane_data import (
    StatisticsView,
    StatisticsViewData,
    VIEW_DESCRIPTIONS,
)
from sase.project_display_names import ProjectDisplaySnapshot
from sase.stats.query import RuntimeGroupBy
from sase.stats.ranges import StatsRange
from sase.stats.views import build_statistics_views

from tests.ace.tui._plugins_browser_pane_helpers import (
    _catalog,
    _patch_catalog,
    _patch_other_panes,
)
from tests._project_display_case import ProjectDisplayCase

_NOW = 1_720_268_400.0


def _run_payload(selected_range: StatsRange, group_by: RuntimeGroupBy) -> dict:
    return {
        "start_ts": selected_range.start_ts,
        "end_ts": selected_range.end_ts,
        "runtime_group_by": group_by,
        "bucket_seconds": 86_400,
        "totals": {
            "runs": 6,
            "completed": 4,
            "failed": 1,
            "other_terminal": 0,
            "in_progress": 1,
            "waiting": 0,
        },
        "outcomes": [
            {"name": "completed", "count": 4},
            {"name": "failed", "count": 1},
        ],
        "retries": {"chains": 1, "attempts": 2, "kills": 0},
        "providers": [
            {
                "provider": "codex",
                "model": "gpt-5.6",
                "effort": "high",
                "runs": 4,
                "success_rate": 0.75,
                "mean_runtime_seconds": 125.0,
            },
            {
                "provider": "claude",
                "model": "opus",
                "effort": "default",
                "runs": 2,
                "success_rate": 0.5,
                "mean_runtime_seconds": 240.0,
            },
        ],
        "commits": {
            "total_commits": 7,
            "committing_agents": 3,
            "average_per_committing_agent": 7 / 3,
            "distribution": {"zero": 3, "one": 1, "two": 1, "three_plus": 1},
            "top_repos": [{"name": "sase", "count": 7}],
        },
        "plans": {
            "proposed": 1,
            "approved": 1,
            "rejected": 0,
            "pending": 0,
        },
        "questions": {"sessions": 1, "asking_agents": 1},
        "workspaces": [{"project": "sase", "workspace_num": 15, "runs": 6}],
        "buckets": [
            {"start_ts": selected_range.start_ts, "runs": 2},
            {"start_ts": selected_range.start_ts + 86_400, "runs": 4},
        ],
        "runtime_groups": [
            {
                "group": "alpha",
                "runs": 3,
                "total_seconds": 600.0,
                "mean_seconds": 200.0,
                "p50_seconds": 180.0,
                "p95_seconds": 290.0,
                "max_seconds": 300.0,
            }
        ],
        "work": {
            "projects": [
                {
                    "project": "sase",
                    "runs": 4,
                    "completed": 3,
                    "failed": 1,
                    "success_rate": 0.75,
                    "commits": 5,
                    "distinct_changespecs": 1,
                    "unattributed_runs": 1,
                    "total_runtime_seconds": 500.0,
                    "last_run_ts": _NOW,
                },
                {
                    "project": "core",
                    "runs": 2,
                    "completed": 1,
                    "failed": 0,
                    "success_rate": 1.0,
                    "commits": 2,
                    "distinct_changespecs": 1,
                    "unattributed_runs": 0,
                    "total_runtime_seconds": 100.0,
                    "last_run_ts": _NOW - 60,
                },
            ],
            "changespecs": [
                {
                    "project": "sase",
                    "name": "statistics-projects",
                    "status": "Ready",
                    "has_pr": True,
                    "runs": 3,
                    "distinct_agents": 2,
                    "commits": 5,
                    "total_runtime_seconds": 420.0,
                    "last_run_ts": _NOW,
                },
                {
                    "project": "core",
                    "name": "stats-wire",
                    "status": "Submitted",
                    "has_pr": True,
                    "runs": 2,
                    "distinct_agents": 1,
                    "commits": 2,
                    "total_runtime_seconds": 100.0,
                    "last_run_ts": _NOW - 60,
                },
            ],
            "unattributed_runs": 1,
            "truncated_changespec_rows": 0,
            "malformed_spec_files_skipped": 0,
        },
    }


def _activity_payload() -> dict:
    return {
        "skills": [{"name": "sase_plan", "count": 8, "distinct_agents": 3}],
        "memories": [{"name": "tui_perf.md", "count": 4, "distinct_agents": 2}],
        "plans": {
            "proposed": 3,
            "tiers": [
                {"name": "epic", "count": 1},
                {"name": "tale", "count": 2},
            ],
            "approved": 2,
            "rejected": 0,
            "pending": 1,
            "phases_per_epic": [{"value": 5, "count": 1}],
            "mean_phases_per_epic": 5.0,
        },
        "questions": {
            "sessions": 2,
            "questions": 3,
            "questions_per_session": [
                {"value": 1, "count": 1},
                {"value": 2, "count": 1},
            ],
            "mean_questions_per_session": 1.5,
        },
    }


def _result(
    view: StatisticsView,
    selected_range: StatsRange,
    group_by: RuntimeGroupBy,
    *,
    empty: bool = False,
    project_filter: str | None = None,
    project_display_snapshot: ProjectDisplaySnapshot | None = None,
    project_display_case: ProjectDisplayCase | None = None,
) -> StatisticsViewData:
    run_payload = {} if empty else _run_payload(selected_range, group_by)
    if project_display_case is not None and run_payload:
        run_payload["workspaces"][0]["project"] = project_display_case.project_key
        run_payload["work"]["projects"][0]["project"] = project_display_case.project_key
        run_payload["work"]["changespecs"][0].update(
            {
                "project": project_display_case.project_key,
                "name": project_display_case.changespec_key,
            }
        )
        if group_by == "project":
            run_payload["runtime_groups"][0]["group"] = project_display_case.project_key
        elif group_by == "changespec":
            run_payload["runtime_groups"][0]["group"] = (
                project_display_case.changespec_key
            )
    activity_payload = {} if empty else _activity_payload()
    display_snapshot = (
        project_display_snapshot
        if project_display_snapshot is not None
        else (
            project_display_case.snapshot
            if project_display_case is not None
            else ProjectDisplaySnapshot()
        )
    )
    return StatisticsViewData(
        view=view,
        selected_range=selected_range,
        runtime_group_by=group_by,
        generated_at=_NOW,
        views=build_statistics_views(
            run_payload,
            activity_payload,
            project_display_snapshot=display_snapshot,
        ),
        project_filter=project_filter,
        project_display_snapshot=display_snapshot,
    )


def _patch_center(
    monkeypatch: pytest.MonkeyPatch,
    calls: list[tuple[StatisticsView, StatsRange, RuntimeGroupBy, str | None]],
    *,
    project_display_case: ProjectDisplayCase | None = None,
) -> None:
    _patch_other_panes(monkeypatch)
    _patch_catalog(monkeypatch, catalog=_catalog())

    def load(
        view: StatisticsView,
        selected_range: StatsRange,
        group_by: RuntimeGroupBy,
        project_filter: str | None = None,
    ) -> StatisticsViewData:
        calls.append((view, selected_range, group_by, project_filter))
        return _result(
            view,
            selected_range,
            group_by,
            project_filter=project_filter,
            project_display_case=project_display_case,
        )

    monkeypatch.setattr(sp, "load_statistics_view", load)


async def _open_statistics(
    page: AcePage,
) -> tuple[ConfigCenterModal, StatisticsPane]:
    modal = ConfigCenterModal(initial_tab="statistics")
    page.app.push_screen(modal)
    await page.expect_modal("ConfigCenterModal")
    await page.wait_for(lambda _state: bool(modal.query("#statistics")))
    pane = modal.query_one("#statistics", StatisticsPane)
    await page.wait_for(lambda _state: not pane._loading and pane._loaded_once)
    return modal, pane


def _scope_plain(pane: StatisticsPane, name: str) -> str:
    return pane.query_one(f"#statistics-scope-{name}", Static).render().plain


def _assert_range_scope_matches_selection(pane: StatisticsPane) -> None:
    scope = _scope_plain(pane, "range")
    assert "Range" in scope
    assert pane._range.display_label in scope
    assert pane._range.label in scope


async def test_statistics_loads_only_after_its_tab_becomes_active(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[tuple[StatisticsView, StatsRange, RuntimeGroupBy, str | None]] = []
    _patch_center(monkeypatch, calls)

    async with AcePage() as page:
        modal = ConfigCenterModal(initial_tab="config")
        page.app.push_screen(modal)
        await page.expect_modal("ConfigCenterModal")
        await page.wait_for(lambda _state: modal._active_tab == "config")
        await page.pause()

        assert calls == []
        assert not modal.query("#statistics")

        await page.press("4")
        await page.wait_for(lambda _state: bool(modal.query("#statistics")))
        pane = modal.query_one("#statistics", StatisticsPane)
        await page.wait_for(lambda _state: pane._loaded_once and not pane._loading)

        assert len(calls) == 1
        assert calls[0][0] == "overview"
        assert calls[0][2] == "tribe"
        _assert_range_scope_matches_selection(pane)
        assert pane._range.display_label == "Last 7 days"
        title = pane.query_one("#statistics-title", Static).render().plain
        status = pane.query_one("#statistics-status", Static).render().plain
        assert title == "Statistics · Overview"
        assert pane._range.label not in title
        assert status.startswith("updated ")


async def test_range_and_group_switches_coalesce_to_latest_selection(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[tuple[StatisticsView, StatsRange, RuntimeGroupBy, str | None]] = []
    _patch_center(monkeypatch, calls)

    async with AcePage() as page:
        _, pane = await _open_statistics(page)
        pane._set_view("runtime")
        pane.action_cycle_range()
        pane.action_cycle_range()
        pane.action_cycle_group()
        await page.wait_for(
            lambda _state: (
                pane._load_debouncer is not None
                and not pane._load_debouncer.is_pending
                and not pane._loading
                and pane._last_result is not None
                and pane._last_result.runtime_group_by == "clan"
            )
        )

        assert len(calls) == 2
        assert calls[-1][0] == "runtime"
        assert calls[-1][1].label == pane._range.label
        assert calls[-1][1].display_label == pane._range.display_label
        assert pane._preset_key == "90d"
        assert pane._range.display_label == "Last 90 days"
        assert pane._runtime_group_by == "clan"
        _assert_range_scope_matches_selection(pane)


async def test_group_cycle_is_view_sensitive_and_projects_reuses_result(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[tuple[StatisticsView, StatsRange, RuntimeGroupBy, str | None]] = []
    _patch_center(monkeypatch, calls)

    async with AcePage() as page:
        _, pane = await _open_statistics(page)
        pane._set_view("projects")
        pane.action_cycle_group()
        await page.pause()

        assert pane._projects_group_by == "changespec"
        assert pane._runtime_group_by == "tribe"
        assert len(calls) == 1
        assert "Projects · By ChangeSpec" in _scope_plain(pane, "group")
        assert "group" not in (
            pane.query_one("#statistics-hints", Static).render().plain
        )

        pane._set_view("runs")
        pane.action_cycle_group()
        await page.pause()
        assert pane._projects_group_by == "changespec"
        assert pane._runtime_group_by == "tribe"
        assert len(calls) == 1
        assert _scope_plain(pane, "group").endswith("Group —")


async def test_project_filter_cycles_ranked_projects_and_survives_range_change(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[tuple[StatisticsView, StatsRange, RuntimeGroupBy, str | None]] = []
    _patch_center(monkeypatch, calls)

    async with AcePage() as page:
        _, pane = await _open_statistics(page)

        pane.action_cycle_project_filter()
        await page.wait_for(lambda _state: len(calls) == 2 and not pane._loading)
        assert pane._project_filter == "sase"
        assert calls[-1][3] == "sase"
        assert "sase" in _scope_plain(pane, "project")
        assert "■" in _scope_plain(pane, "project")
        assert "sase" not in (
            pane.query_one("#statistics-title", Static).render().plain
        )

        pane.action_cycle_range()
        await page.wait_for(lambda _state: len(calls) == 3 and not pane._loading)
        assert calls[-1][1].label == pane._range.label
        assert calls[-1][1].display_label == pane._range.display_label
        assert calls[-1][3] == "sase"
        _assert_range_scope_matches_selection(pane)

        pane.action_cycle_project_filter()
        await page.wait_for(lambda _state: len(calls) == 4 and not pane._loading)
        assert pane._project_filter == "core"
        assert calls[-1][3] == "core"

        pane.action_cycle_project_filter()
        await page.wait_for(lambda _state: len(calls) == 5 and not pane._loading)
        assert pane._project_filter is None
        assert calls[-1][3] is None


async def test_project_filter_label_submits_canonical_key_across_reload_paths(
    monkeypatch: pytest.MonkeyPatch,
    project_display_case: ProjectDisplayCase,
) -> None:
    calls: list[tuple[StatisticsView, StatsRange, RuntimeGroupBy, str | None]] = []
    _patch_other_panes(monkeypatch)
    _patch_catalog(monkeypatch, catalog=_catalog())
    widgets_key = project_display_case.project_key
    snapshot = project_display_case.snapshot

    def load(
        view: StatisticsView,
        selected_range: StatsRange,
        group_by: RuntimeGroupBy,
        project_filter: str | None = None,
    ) -> StatisticsViewData:
        calls.append((view, selected_range, group_by, project_filter))
        payload = _run_payload(selected_range, group_by)
        payload["workspaces"][0]["project"] = widgets_key
        payload["work"]["projects"][0]["project"] = widgets_key
        payload["work"]["changespecs"][0]["project"] = widgets_key
        return StatisticsViewData(
            view=view,
            selected_range=selected_range,
            runtime_group_by=group_by,
            generated_at=_NOW,
            views=build_statistics_views(
                payload,
                _activity_payload(),
                project_display_snapshot=snapshot,
            ),
            project_filter=project_filter,
            project_display_snapshot=snapshot,
        )

    monkeypatch.setattr(sp, "load_statistics_view", load)

    async with AcePage() as page:
        _, pane = await _open_statistics(page)

        pane.action_cycle_project_filter()
        await page.wait_for(lambda _state: len(calls) == 2 and not pane._loading)
        project_scope = _scope_plain(pane, "project")
        assert pane._project_filter == widgets_key
        assert calls[-1][3] == widgets_key
        assert project_display_case.project_label in project_scope
        assert widgets_key not in project_scope

        pane.action_cycle_range()
        await page.wait_for(lambda _state: len(calls) == 3 and not pane._loading)
        assert calls[-1][3] == widgets_key

        pane.action_refresh()
        await page.wait_for(lambda _state: len(calls) == 4 and not pane._loading)
        assert calls[-1][3] == widgets_key


def test_stale_project_filter_result_is_discarded_and_rescheduled(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    pane = StatisticsPane(auto_load=False)
    pane._project_filter = "core"
    result = _result(
        pane._view,
        pane._range,
        pane._runtime_group_by,
        project_filter="sase",
    )
    worker = SimpleNamespace(result=result, error=None)
    pane._worker = worker  # type: ignore[assignment]
    scheduled: list[bool] = []
    monkeypatch.setattr(pane, "_schedule_load", lambda: scheduled.append(True))

    pane.on_worker_state_changed(
        SimpleNamespace(worker=worker, state=WorkerState.SUCCESS)  # type: ignore[arg-type]
    )

    assert scheduled == [True]
    assert pane._last_result is None


def _render_plain(renderable: object) -> str:
    console = Console(width=180, color_system=None)
    with console.capture() as capture:
        console.print(renderable)
    return capture.get()


def test_renderers_use_projected_labels_and_canonical_project_colors(
    monkeypatch: pytest.MonkeyPatch,
    project_display_case: ProjectDisplayCase,
) -> None:
    widgets_key = project_display_case.project_key
    changespec_key, changespec_label = project_display_case.changespec(
        "statistics-projects"
    )
    snapshot = project_display_case.snapshot
    payload = _run_payload(StatsRange(0, 100, "absolute", "Test"), "project")
    payload["workspaces"][0]["project"] = widgets_key
    payload["work"]["projects"][0]["project"] = widgets_key
    payload["work"]["changespecs"][0].update(
        {"project": widgets_key, "name": changespec_key}
    )
    payload["runtime_groups"][0]["group"] = widgets_key
    views = build_statistics_views(
        payload,
        _activity_payload(),
        project_display_snapshot=snapshot,
    )
    color_keys: list[str] = []

    def color_for(key: str) -> str:
        color_keys.append(key)
        return "#87D7FF"

    monkeypatch.setattr(
        "sase.ace.tui.modals.statistics_pane_projects.categorical_color",
        color_for,
    )
    pane = StatisticsPane(auto_load=False)

    overview = _render_plain(pane._overview_renderable(views.overview))
    activity = _render_plain(pane._activity_renderable(views.activity))
    runtime = _render_plain(pane._runtime_renderable(views.runtime))
    project_surfaces: list[str] = []
    for group_by in ("project", "changespec", "drilldown"):
        pane._projects_group_by = group_by  # type: ignore[assignment]
        project_surfaces.append(
            _render_plain(pane._projects_renderable(views.projects))
        )

    assert project_display_case.project_label in overview
    assert f"{project_display_case.project_label} · 15" in activity
    assert project_display_case.project_label in runtime
    assert all(
        project_display_case.project_label in rendered for rendered in project_surfaces
    )
    assert changespec_label in "\n".join(project_surfaces)
    assert widgets_key not in "\n".join(
        (overview, activity, runtime, *project_surfaces)
    )
    assert widgets_key in color_keys


def test_all_project_plan_and_question_values_need_no_scope_markers() -> None:
    pane = StatisticsPane(auto_load=False)
    view = _result(pane._view, pane._range, pane._runtime_group_by).views

    columns = pane._plans_questions_renderable(view.plans_questions)
    rendered = _render_plain(columns)

    assert [panel.title for panel in columns.renderables] == ["Plans", "Questions"]
    assert "all projects" not in rendered
    assert "Proposed  1  ·  Approved  1  ·  Rejected  0  ·  Pending  0" in rendered
    assert "Sessions  1  ·  Asking agents  1  ·  Questions  3" in rendered


def test_project_filter_marks_only_global_plan_and_question_values() -> None:
    pane = StatisticsPane(auto_load=False)
    pane._project_filter = "sase"
    view = _result(pane._view, pane._range, pane._runtime_group_by).views

    columns = pane._plans_questions_renderable(view.plans_questions)
    rendered = _render_plain(columns)

    assert [panel.title for panel in columns.renderables] == ["Plans", "Questions"]
    assert "Proposed  1  ·  Approved  1  ·  Rejected  0  ·  Pending  0" in rendered
    assert "Sessions  1  ·  Asking agents  1" in rendered
    assert "Tier (all projects)" in rendered
    assert "Mean phases per epic (all projects): 5.00" in rendered
    assert "Phases (all projects)" in rendered
    assert "Questions (all projects): 3" in rendered
    assert "Mean questions per session (all projects): 1.50" in rendered
    assert "Questions (all projects)" in rendered


async def test_view_cycle_reuses_composite_result_and_updates_strip(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[tuple[StatisticsView, StatsRange, RuntimeGroupBy, str | None]] = []
    _patch_center(monkeypatch, calls)

    async with AcePage() as page:
        _, pane = await _open_statistics(page)
        await page.press("right_square_bracket", "right_square_bracket")
        await page.wait_for(lambda _state: pane._view == "projects")

        assert len(calls) == 1
        assert (
            pane.query_one("#statistics-description", Static).render().plain
            == f"› {VIEW_DESCRIPTIONS['projects']}"
        )

        await page.press("right_square_bracket")
        await page.wait_for(lambda _state: pane._view == "providers")
        await page.press("left_square_bracket")
        await page.wait_for(lambda _state: pane._view == "projects")
        assert len(calls) == 1


async def test_refresh_preserves_selection_and_hidden_tick_is_inert(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[tuple[StatisticsView, StatsRange, RuntimeGroupBy, str | None]] = []
    _patch_center(monkeypatch, calls)

    async with AcePage() as page:
        modal, pane = await _open_statistics(page)
        pane._set_view("runtime")
        pane.action_cycle_group()
        await page.wait_for(lambda _state: len(calls) == 2 and not pane._loading)
        await page.press("r")
        await page.wait_for(lambda _state: len(calls) == 3 and not pane._loading)

        assert calls[-1][0] == "runtime"
        assert calls[-1][2] == "clan"
        _assert_range_scope_matches_selection(pane)
        await modal._switch_to("config")
        pane._on_refresh_tick()
        await page.pause()
        assert len(calls) == 3
        assert pane._load_debouncer is not None
        assert not pane._load_debouncer.is_pending


async def test_custom_range_accepts_valid_input_and_rejects_invalid_input(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[tuple[StatisticsView, StatsRange, RuntimeGroupBy, str | None]] = []
    _patch_center(monkeypatch, calls)

    async with AcePage() as page:
        _, pane = await _open_statistics(page)
        await page.press("c")
        custom_input = pane.query_one("#statistics-custom-range", Input)
        assert custom_input.display is True
        custom_input.value = "14d"
        await page.press("enter")
        await page.wait_for(lambda _state: len(calls) == 2 and not pane._loading)

        assert pane._preset_key is None
        assert pane._custom_range_value == "14d"
        assert custom_input.display is False
        assert pane._range.display_label == "Last 14 days"
        custom_scope = _scope_plain(pane, "range")
        _assert_range_scope_matches_selection(pane)
        assert "Custom · Last 14 days" in custom_scope

        accepted_range = pane._range
        await page.press("c")
        custom_input.value = "not-a-range"
        await page.press("enter")
        await page.pause()

        assert pane._range == accepted_range
        assert len(calls) == 2
        assert custom_input.display is True
        _assert_range_scope_matches_selection(pane)


async def test_configured_bindings_dispatch_and_render_effective_help(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[tuple[StatisticsView, StatsRange, RuntimeGroupBy, str | None]] = []
    _patch_center(monkeypatch, calls)
    registry = load_keymap_registry(
        {
            "keymaps": {
                "statistics": {
                    "prev_view": "f12",
                    "next_view": "f11",
                    "cycle_range": "f10",
                    "custom_range": "f9",
                    "cycle_group": "f8",
                    "cycle_project_filter": "f7",
                    "refresh": "f6",
                    "help": "f5",
                }
            }
        }
    )

    assert statistics_help_bindings(registry.statistics) == [
        ("f12", "Previous View"),
        ("f11", "Next View"),
        ("f10", "Time Range"),
        ("f9", "Custom Range"),
        ("f8", "Group By"),
        ("f7", "Project Filter"),
        ("f6", "Refresh"),
        ("f5", "Help"),
    ]

    async with AcePage() as page:
        page.app._keymap_registry = registry
        _, pane = await _open_statistics(page)

        hints = pane.query_one("#statistics-hints", Static).render().plain
        assert hints == "f12 / f11 views   f9 custom range   f6 refresh   f5 help"
        assert _scope_plain(pane, "range").startswith(" f10  Range ")
        assert _scope_plain(pane, "group").startswith(" f8  Group ")
        assert _scope_plain(pane, "project").startswith(" f7  Project ")
        await page.press("f11", "f11", "f8")
        await page.wait_for(
            lambda _state: (
                pane._view == "projects" and pane._projects_group_by == "changespec"
            )
        )
        assert len(calls) == 1


async def test_statistics_help_opens_and_closes_from_configured_binding(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[tuple[StatisticsView, StatsRange, RuntimeGroupBy, str | None]] = []
    _patch_center(monkeypatch, calls)
    registry = load_keymap_registry({"keymaps": {"statistics": {"help": "f5"}}})

    async with AcePage() as page:
        page.app._keymap_registry = registry
        _, pane = await _open_statistics(page)

        await page.press("f5")
        await page.expect_modal("StatisticsHelpModal")
        assert isinstance(page.app.screen, StatisticsHelpModal)

        await page.press("question_mark")
        await page.expect_modal("ConfigCenterModal")
        assert pane.is_mounted


async def test_statistics_bindings_are_inactive_on_other_admin_center_tabs(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[tuple[StatisticsView, StatsRange, RuntimeGroupBy, str | None]] = []
    _patch_center(monkeypatch, calls)
    registry = load_keymap_registry(
        {"keymaps": {"statistics": {"cycle_group": "f12", "help": "f5"}}}
    )

    async with AcePage() as page:
        page.app._keymap_registry = registry
        modal = ConfigCenterModal(initial_tab="config")
        page.app.push_screen(modal)
        await page.expect_modal("ConfigCenterModal")
        await page.wait_for(lambda _state: modal._active_tab == "config")
        assert not modal.query("#statistics")

        await page.press("f12")
        await page.press("f5")
        await page.pause()

        assert modal._active_tab == "config"
        assert not modal.query("#statistics")
        assert calls == []
        assert isinstance(page.app.screen, ConfigCenterModal)


async def test_auto_refresh_soak_keeps_event_loop_and_message_pump_responsive(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    project_display_case: ProjectDisplayCase,
) -> None:
    stall_log = tmp_path / "tui_stalls.jsonl"
    monkeypatch.setenv("SASE_TUI_STALL_PATH", str(stall_log))
    monkeypatch.setenv("SASE_TUI_HITCH_THRESHOLD_SECONDS", "0.5")
    monkeypatch.setenv("SASE_TUI_PUMP_HITCH_THRESHOLD_SECONDS", "0.5")
    monkeypatch.setenv("SASE_TUI_STALL_THRESHOLD_SECONDS", "1.0")
    monkeypatch.setenv("SASE_TUI_PUMP_STALL_THRESHOLD_SECONDS", "1.0")
    monkeypatch.setenv("SASE_TUI_STALL_POLL_INTERVAL", "0.02")
    monkeypatch.setenv("SASE_TUI_PUMP_STALL_POLL_INTERVAL", "0.02")
    monkeypatch.setattr(sp, "_REFRESH_INTERVAL_SECONDS", 0.2)

    calls: list[tuple[StatisticsView, StatsRange, RuntimeGroupBy, str | None]] = []
    _patch_center(
        monkeypatch,
        calls,
        project_display_case=project_display_case,
    )

    async with AcePage() as page:
        _, pane = await _open_statistics(page)
        await asyncio.sleep(1.1)
        await page.wait_for(lambda _state: not pane._loading)

        assert len(calls) >= 4
        assert all(call[0] == "overview" for call in calls)
        assert pane._last_result is not None
        rendered = _render_plain(
            pane._overview_renderable(pane._last_result.views.overview)
        )
        assert project_display_case.project_label in rendered
        assert project_display_case.project_key not in rendered

    assert not stall_log.exists() or not stall_log.read_text().strip()


def test_loader_queries_current_activity_and_previous_equal_window(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[tuple[str, int, int, str | None]] = []
    selected_range = StatsRange(10, 20, "absolute", "Last 10 seconds")
    display_snapshot = ProjectDisplaySnapshot({"sase": "SASE Display"})
    snapshot_loads = 0

    def load_snapshot() -> ProjectDisplaySnapshot:
        nonlocal snapshot_loads
        snapshot_loads += 1
        return display_snapshot

    def run_query(**kwargs: int | str | None) -> dict:
        calls.append(
            (
                "runs",
                int(kwargs["start_ts"]),  # type: ignore[arg-type]
                int(kwargs["end_ts"]),  # type: ignore[arg-type]
                kwargs.get("project"),  # type: ignore[arg-type]
            )
        )
        return _run_payload(selected_range, "tribe")

    def activity_query(**kwargs: int | str | None) -> dict:
        calls.append(
            (
                "activity",
                int(kwargs["start_ts"]),  # type: ignore[arg-type]
                int(kwargs["end_ts"]),  # type: ignore[arg-type]
                kwargs.get("project"),  # type: ignore[arg-type]
            )
        )
        return _activity_payload()

    monkeypatch.setattr(
        "sase.ace.tui.modals.statistics_pane_data.query_run_stats", run_query
    )
    monkeypatch.setattr(
        "sase.ace.tui.modals.statistics_pane_data.query_activity_stats",
        activity_query,
    )
    monkeypatch.setattr(
        "sase.ace.tui.modals.statistics_pane_data.load_project_display_snapshot",
        load_snapshot,
    )

    result = sp.load_statistics_view("overview", selected_range, "tribe", "sase")

    assert calls == [
        ("runs", 10, 20, "sase"),
        ("activity", 10, 20, "sase"),
        ("runs", 0, 10, "sase"),
    ]
    assert result.views.overview.agents_run == 6
    assert result.project_filter == "sase"
    assert snapshot_loads == 1
    assert result.project_display_snapshot is display_snapshot
    assert result.views.projects.projects[0].project_label == "SASE Display"
