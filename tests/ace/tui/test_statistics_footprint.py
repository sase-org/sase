"""Statistics pane coverage for Footprint actor, lens, and area navigation."""

from __future__ import annotations

import threading
from types import SimpleNamespace
from typing import Any
from unittest.mock import PropertyMock, patch

import pytest
from rich.columns import Columns
from textual.geometry import Size
from textual.widgets import OptionList, Static
from textual.worker import WorkerState

from sase.ace.testing import AcePage
from sase.ace.tui.modals.statistics_pane import StatisticsPane
from tests.ace.tui._statistics_pane_helpers import (
    _open_statistics,
    _patch_center,
    _render_plain,
    _result,
    _wait_statistics_settled,
)


async def test_footprint_view_cycles_actor_and_lens(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[tuple[object, ...]] = []
    _patch_center(monkeypatch, calls)

    async with AcePage() as page:
        _, pane = await _open_statistics(page)
        pane._set_view("footprint")
        await _wait_statistics_settled(page, pane)

        assert pane._footprint_lens == "map"
        assert pane._footprint_actor == "you"
        assert pane.query_one("#statistics-tiles").display is True
        assert _scope_actor(pane) == "You"
        report = pane._last_result.footprint if pane._last_result is not None else None
        assert report is not None
        assert report["header"]["actor"] == "you"
        assert "PREVIEW" in _render_plain(pane._view_renderable(pane._last_result))

        await page.press("a")
        await _wait_statistics_settled(page, pane)
        assert pane._footprint_actor == "agents"
        assert _scope_actor(pane) == "Agents"
        assert pane._last_result is not None
        assert pane._last_result.footprint["header"]["actor"] == "agents"

        await page.press("g")
        await _wait_statistics_settled(page, pane)
        assert pane._footprint_lens == "cold"
        assert pane._last_result is not None
        assert pane._last_result.footprint_lens == "cold"


async def test_footprint_rows_drill_into_and_back_out_of_an_area(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[tuple[object, ...]] = []
    _patch_center(monkeypatch, calls)

    async with AcePage() as page:
        _, pane = await _open_statistics(page)
        pane._set_view("footprint")
        await _wait_statistics_settled(page, pane)

        assert pane._footprint_items()[0]["area"] == "cli.bead"
        await page.press("j")
        assert pane._footprint_selected_index == 1
        assert pane._footprint_items()[pane._footprint_selected_index]["area"] == (
            "tui.statistics"
        )

        await page.press("enter")
        await _wait_statistics_settled(page, pane)
        assert pane._footprint_area == "tui.statistics"
        assert pane._last_result is not None
        assert pane._last_result.footprint_area == "tui.statistics"
        assert "tui:statistics.cycle_range" in _render_plain(
            pane._view_renderable(pane._last_result)
        )

        await page.press("backspace")
        await _wait_statistics_settled(page, pane)
        assert pane._footprint_area is None
        assert "Surface map" in _render_plain(pane._view_renderable(pane._last_result))


def _scope_actor(pane: StatisticsPane) -> str:
    text = pane.query_one("#statistics-scope-actor", Static).render().plain
    return text.split("Actor ", 1)[-1].strip()


def _feature_card(state: str = "used", **overrides: Any) -> dict[str, Any]:
    row: dict[str, Any] = {
        "id": "cli:bead.list",
        "label": "bead list",
        "ns": "cli",
        "area": "cli.bead",
        "kind": "command",
        "state": state,
        "uses": {"human": 9, "agent": 4, "automation": 0},
        "days_used": 5,
        "last_used_day": "2026-10-27",
        "last_used_actor": "human",
        "via": {"cli": 13},
        "loc": 520,
        "protected": None,
        "decision": None,
        "decision_reason": None,
        "coverage_incomplete": False,
    }
    row.update(overrides)
    return {
        "row": row,
        "daily_series": [{"day": "2026-10-27", "n": 3, "measured": True}],
        "first_in_catalog": "2026-08-01",
        "last_in_catalog": "2026-10-27",
        "parent": None,
        "children": ["cli:bead.list#json"],
        "retire_with": [],
        "area_summary": None,
    }


def _area_card() -> dict[str, Any]:
    card = _feature_card()
    card["row"] = {
        "id": "cli.bead",
        "label": "cli.bead",
        "ns": "cli",
        "area": "cli.bead",
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
    }
    card["area_summary"] = {
        "area": "cli.bead",
        "ns": "cli",
        "total": 10,
        "used": 6,
        "used_pct": 60,
        "recency_7d": 2,
        "recency_30d": 2,
        "recency_window": 2,
        "recency_none": 3,
        "recency_not_measured": 1,
        "unused_by_loc": [
            {
                "id": "cli:bead.close",
                "label": "bead close",
                "ns": "cli",
                "area": "cli.bead",
                "kind": "command",
                "loc": 210,
            },
        ],
    }
    return card


def _card_pane(size: Size | None = None) -> StatisticsPane:
    pane = StatisticsPane(auto_load=False)
    pane._view = "footprint"
    pane._last_result = _result("footprint", pane._range)
    if size is not None:
        patcher = patch.object(
            StatisticsPane, "size", new_callable=PropertyMock, return_value=size
        )
        patcher.start()
        pane._size_patcher = patcher  # type: ignore[attr-defined]
    return pane


def _stop_size_patch(pane: StatisticsPane) -> None:
    patcher = getattr(pane, "_size_patcher", None)
    if patcher is not None:
        patcher.stop()


def test_footprint_card_target_follows_lens_and_selection() -> None:
    pane = StatisticsPane(auto_load=False)
    pane._view = "footprint"
    pane._last_result = _result("footprint", pane._range)

    assert pane._footprint_card_target() == ("area", "cli.bead")
    pane._footprint_selected_index = 1
    assert pane._footprint_card_target() == ("area", "tui.statistics")

    pane._footprint_area = "cli.bead"
    pane._footprint_selected_index = 0
    assert pane._footprint_card_target() == ("feature", "cli:bead.list")

    pane._footprint_area = None
    pane._footprint_lens = "coverage"
    assert pane._footprint_card_target() is None

    pane._view = "overview"
    pane._footprint_lens = "map"
    assert pane._footprint_card_target() is None


def test_footprint_card_renders_each_evidence_state() -> None:
    for state, phrase in (
        ("used", "Used by you on 5 of 12 observed active days"),
        ("no_recorded_use", "No recorded use by you across 12 observed active days"),
        ("rare_by_design", "Rare by design"),
    ):
        pane = _card_pane()
        try:
            pane._footprint_card = _feature_card(state)
            pane._footprint_card_for = ("feature", "cli:bead.list")
            pane._footprint_lens = "cold"
            rendered = _render_plain(pane._view_renderable(pane._last_result))
            assert phrase in rendered, state
            assert "k keep · l later · x cut · u undo · F finish review" in rendered
        finally:
            _stop_size_patch(pane)


def test_footprint_card_wide_sits_beside_list_narrow_stacks() -> None:
    wide = _card_pane(Size(130, 40))
    try:
        wide._footprint_card = _area_card()
        wide._footprint_card_for = ("area", "cli.bead")
        renderable = wide._view_renderable(wide._last_result)
        assert isinstance(renderable.renderables[1], Columns)
        assert "Largest unused by LOC" in _render_plain(renderable)
    finally:
        _stop_size_patch(wide)

    narrow = _card_pane(Size(90, 30))
    try:
        narrow._footprint_card = _area_card()
        narrow._footprint_card_for = ("area", "cli.bead")
        renderable = narrow._view_renderable(narrow._last_result)
        assert not isinstance(renderable.renderables[1], Columns)
        plain = _render_plain(renderable)
        assert "Largest unused by LOC" in plain
        assert "cli:bead.close" in plain
    finally:
        _stop_size_patch(narrow)


def test_footprint_card_narrow_rows_hide_secondary_columns() -> None:
    pane = _card_pane(Size(90, 30))
    try:
        rendered = _render_plain(pane._view_renderable(pane._last_result))
        assert "cli.bead" in rendered
        pane._footprint_area = "cli.bead"
        drilled = _render_plain(pane._view_renderable(pane._last_result))
        assert "bead list" in drilled
        assert "via cli" not in drilled
    finally:
        _stop_size_patch(pane)


def test_footprint_card_loading_error_and_coverage_states() -> None:
    pane = _card_pane()
    try:
        rendered = _render_plain(pane._view_renderable(pane._last_result))
        assert "Loading evidence…" in rendered

        pane._footprint_card_error = "card load failed"
        rendered = _render_plain(pane._view_renderable(pane._last_result))
        assert "Evidence unavailable." in rendered

        pane._footprint_card_error = ""
        pane._footprint_lens = "coverage"
        rendered = _render_plain(pane._view_renderable(pane._last_result))
        assert "Evidence" not in rendered
        assert "dropped 1" in rendered
    finally:
        _stop_size_patch(pane)


def test_footprint_card_stale_generation_is_dropped() -> None:
    pane = StatisticsPane(auto_load=False)
    pane._view = "footprint"
    pane._last_result = _result("footprint", pane._range)
    pane._footprint_card_generation = 2

    stale = SimpleNamespace(
        state=WorkerState.SUCCESS,
        worker=SimpleNamespace(
            result=(1, ("area", "cli.bead"), _feature_card()), error=None
        ),
    )
    pane._on_footprint_card_worker_state(stale)
    assert pane._footprint_card is None

    mismatched = SimpleNamespace(
        state=WorkerState.SUCCESS,
        worker=SimpleNamespace(
            result=(2, ("feature", "cli:nope.missing"), _feature_card()), error=None
        ),
    )
    pane._on_footprint_card_worker_state(mismatched)
    assert pane._footprint_card is None

    pane._footprint_selected_index = 1
    current = SimpleNamespace(
        state=WorkerState.SUCCESS,
        worker=SimpleNamespace(
            result=(2, ("area", "tui.statistics"), _area_card()), error=None
        ),
    )
    pane._on_footprint_card_worker_state(current)
    assert pane._footprint_card_for == ("area", "tui.statistics")
    assert pane._footprint_card is not None


async def test_footprint_card_reloads_after_row_move(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import sase.ace.tui.modals.statistics_pane_footprint as footprint_render

    monkeypatch.setattr(
        footprint_render,
        "fetch_footprint_card",
        lambda target, **kwargs: dict(_area_card()),
    )
    calls: list[tuple[object, ...]] = []
    _patch_center(monkeypatch, calls)

    async with AcePage() as page:
        _, pane = await _open_statistics(page)
        pane._set_view("footprint")
        await _wait_statistics_settled(page, pane)
        await page.wait_for(lambda _state: pane._footprint_card is not None)
        assert pane._footprint_card_for == ("area", "cli.bead")

        await page.press("j")
        await page.wait_for(
            lambda _state: pane._footprint_card_for == ("area", "tui.statistics")
        )


async def test_footprint_copy_sends_selected_feature_id(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import sase.ace.tui.actions.clipboard as clipboard

    copied: list[tuple[str, dict[str, Any]]] = []
    monkeypatch.setattr(
        clipboard,
        "schedule_copy_delivery",
        lambda app, value, **kwargs: copied.append((value, kwargs)) or None,
    )
    calls: list[tuple[object, ...]] = []
    _patch_center(monkeypatch, calls)

    async with AcePage() as page:
        _, pane = await _open_statistics(page)
        pane._set_view("footprint")
        await _wait_statistics_settled(page, pane)

        await page.press("y")
        await page.wait_for(lambda _state: bool(copied))
        assert copied[0][0] == "cli.bead"

        pane._footprint_selected_index = 1
        await page.press("enter")
        await _wait_statistics_settled(page, pane)
        assert pane._footprint_area == "tui.statistics"
        copied.clear()
        await page.press("y")
        await page.wait_for(lambda _state: bool(copied))
        assert copied[0][0] == "tui:statistics.cycle_range"
        assert copied[0][1]["copied_label"] == "Feature ID"


async def test_footprint_keep_reason_is_recorded_by_a_worker(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from sase.footprint import query as footprint_query

    writes: list[tuple[int, str, str, str | None]] = []
    main_thread = threading.get_ident()

    def record_decision(
        feature_id: str,
        decision: str,
        reason: str | None,
    ) -> dict[str, str | None]:
        writes.append((threading.get_ident(), feature_id, decision, reason))
        return {"feature_id": feature_id, "decision": decision, "reason": reason}

    monkeypatch.setattr(footprint_query, "record_decision", record_decision)
    calls: list[tuple[object, ...]] = []
    _patch_center(monkeypatch, calls)

    async with AcePage() as page:
        _, pane = await _open_statistics(page)
        pane._set_view("footprint")
        await _wait_statistics_settled(page, pane)
        await page.press("enter")
        await _wait_statistics_settled(page, pane)

        await page.press("k")
        await page.expect_modal("StatisticsFootprintKeepReasonModal")
        await page.press("enter")
        await page.wait_for(lambda _state: bool(writes))

    thread_id, feature_id, decision, reason = writes[0]
    assert thread_id != main_thread
    assert feature_id == "cli:bead.list"
    assert decision == "keep"
    assert reason == "rare_by_design"


async def test_footprint_finish_review_requires_confirmation_and_launches_macro(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from sase.footprint import query as footprint_query

    request: dict[str, object] = {}
    report = {
        "header": {"window_start": "2026-08-28", "window_end": "2026-10-27"},
        "rows": [
            {"id": "cli:keep", "decision": "keep"},
            {"id": "cli:later", "decision": "later"},
            {"id": "cli:cut", "decision": "cut"},
        ],
    }
    monkeypatch.setattr(
        footprint_query,
        "build_report_request",
        lambda **kwargs: request.update(kwargs) or kwargs,
    )
    monkeypatch.setattr(footprint_query, "fetch_report", lambda _request: report)
    monkeypatch.setattr(
        "sase.footprint.render.review_markdown",
        lambda _report: "# Marked Footprint decisions",
    )
    calls: list[tuple[object, ...]] = []
    _patch_center(monkeypatch, calls)

    async with AcePage() as page:
        _, pane = await _open_statistics(page)
        pane._set_view("footprint")
        await _wait_statistics_settled(page, pane)

        setup_calls: list[dict[str, object]] = []
        launches: list[tuple[str, dict[str, object]]] = []
        monkeypatch.setattr(
            page.app,
            "_setup_home_prompt_context",
            lambda **kwargs: setup_calls.append(kwargs),
        )
        monkeypatch.setattr(
            page.app,
            "_finish_agent_launch",
            lambda prompt, **kwargs: launches.append((prompt, kwargs)),
        )

        pane.action_finish_footprint_review()
        await page.expect_modal("StatisticsFootprintFinishReviewModal")
        assert not launches
        assert request == {
            "lens": "decisions",
            "actor": "everyone",
            "window_days": None,
        }
        summary = page.app.screen.query_one(
            "#statistics-footprint-finish-summary", Static
        ).render()
        assert "1 keep · 1 later · 1 cut" in summary.plain

        await page.press("escape")
        assert not launches

        pane.action_finish_footprint_review()
        await page.expect_modal("StatisticsFootprintFinishReviewModal")
        await page.press("enter")
        await page.wait_for(lambda _state: bool(launches))

    assert setup_calls == [
        {
            "display_name": "Footprint review",
            "history_sort_key": "footprint-review",
            "prompt_origin": "generated",
        }
    ]
    assert launches == [
        (
            "+sase\n#footprint_review::\n\n# Marked Footprint decisions",
            {"prompt_origin": "generated"},
        )
    ]


async def test_footprint_finder_filters_and_drills_to_area(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import sase.ace.tui.modals.statistics_footprint_finder_modal as finder_modal

    monkeypatch.setattr(
        finder_modal,
        "catalog_features",
        lambda: (
            finder_modal.FinderFeature(
                "cli:bead.list", "bead list", "cli.bead", "command"
            ),
            finder_modal.FinderFeature(
                "tui:statistics.cycle_range",
                "Cycle Statistics range",
                "tui.statistics",
                "action",
            ),
        ),
    )
    calls: list[tuple[object, ...]] = []
    _patch_center(monkeypatch, calls)

    async with AcePage() as page:
        _, pane = await _open_statistics(page)
        pane._set_view("footprint")
        await _wait_statistics_settled(page, pane)

        await page.press("slash")
        await page.expect_modal("StatisticsFootprintFinderModal")
        await page.press("b", "e", "a", "d")
        await page.wait_for(
            lambda _state: (
                page.app.screen.query_one(
                    "#statistics-footprint-finder-list", OptionList
                ).option_count
                == 1
            )
        )
        await page.press("enter")
        await _wait_statistics_settled(page, pane)
        assert pane._footprint_lens == "map"
        assert pane._footprint_area == "cli.bead"
        items = pane._footprint_items()
        assert items[pane._footprint_selected_index]["id"] == "cli:bead.list"


def test_footprint_finder_matches_label_or_id() -> None:
    from sase.ace.tui.modals.statistics_footprint_finder_modal import (
        FinderFeature,
        StatisticsFootprintFinderModal,
    )

    feature = FinderFeature("cli:bead.list", "bead list", "cli.bead", "command")
    modal = StatisticsFootprintFinderModal((feature,))
    assert modal._matches(feature, "")
    assert modal._matches(feature, "bead")
    assert modal._matches(feature, "BEAD.LIST")
    assert modal._matches(feature, "cli:bead")
    assert not modal._matches(feature, "statistics")
    assert modal._finder_state() == {
        "total": 1,
        "filtered": ["cli:bead.list"],
    }


def test_footprint_empty_and_unmeasured_states_are_explicit() -> None:
    from dataclasses import replace

    from tests.ace.tui._statistics_pane_helpers import _result

    pane = StatisticsPane(auto_load=False)
    pane._view = "footprint"
    result = _result("footprint", pane._range, empty=True)
    empty = _render_plain(pane._view_renderable(result))
    assert "No Footprint catalog has been ingested yet" in empty
    assert "cannot distinguish untracked features from no recorded use" in empty

    populated_result = _result("footprint", pane._range)
    pane._last_result = populated_result
    pane._footprint_lens = "map"
    populated = _render_plain(pane._view_renderable(populated_result))
    assert "mobile" in populated
    assert "? not measured" in populated

    pane._footprint_lens = "coverage"
    coverage_result = replace(populated_result, footprint_lens="coverage")
    coverage = _render_plain(pane._view_renderable(coverage_result))
    assert "cli" in coverage and "dropped 1" in coverage
    assert "tui" in coverage and "torn 1" in coverage
