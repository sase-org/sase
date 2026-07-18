"""Live filter integration coverage for the Artifacts Plans pane."""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path
from unittest.mock import Mock

import pytest
from textual.widgets import OptionList, Static

from sase.ace.testing import AcePage
from sase.ace.tui.widgets.artifacts.plan_filter_bar import PlanFilterBar
from sase.ace.tui.widgets.artifacts.plans_data import PlansSnapshot, ProjectIssue
from sase.ace.tui.widgets.artifacts.plans_pane import ArtifactsPlansPane
from sase.ace.tui.widgets.single_line_vim_text_area import SingleLineVimTextArea

from .test_artifacts_plans import _choices, _snapshot


async def test_plans_filter_bar_live_filters_tree_commits_and_survives_refresh(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    snapshot = _snapshot(tmp_path)
    refreshed_phase = replace(
        snapshot.phases_by_epic[("alpha", "alpha-1")][0].issue,
        title="Load plans after refresh",
    )
    refreshed = replace(
        snapshot,
        phases_by_epic={
            **snapshot.phases_by_epic,
            ("alpha", "alpha-1"): (
                ProjectIssue("alpha", refreshed_phase),
                snapshot.phases_by_epic[("alpha", "alpha-1")][1],
            ),
        },
        source_key=("fixture-refreshed",),
    )
    current_snapshot = [snapshot]
    load_calls: list[str | None] = []
    monkeypatch.setattr(
        "sase.ace.tui.actions.artifacts._collect_artifacts_project_choices",
        _choices,
    )

    def load(project: str | None, **_kwargs: object) -> PlansSnapshot:
        load_calls.append(project)
        return current_snapshot[0]

    monkeypatch.setattr(
        "sase.ace.tui.widgets.artifacts.plans_pane.load_plans_snapshot",
        load,
    )

    async with AcePage(initial_tab="changespecs") as page:
        await page.press("[")
        pane = page.query_one_widget("#artifacts-plans-pane", ArtifactsPlansPane)
        await page.wait_for(lambda _state: pane.snapshot is snapshot)
        baseline_loads = len(load_calls)
        bar = pane.query_one(PlanFilterBar)
        editor = bar.query_one("#plan-filter-input", SingleLineVimTextArea)

        await page.press("slash")
        await page.wait_for(lambda _state: bar.display)
        assert editor.text == ""
        assert page.app.focused is not None
        assert page.app.focused.id == "plan-filter-input"

        await page.press("l", "o", "a", "d")

        def filtered_ids() -> set[str]:
            options = pane.query_one("#plans-list", OptionList)
            return {
                options.get_option_at_index(index).id or ""
                for index in range(options.option_count)
            }

        await page.wait_for(
            lambda _state: (
                "phase:alpha-1.1" in filtered_ids()
                and "phase:alpha-1.2" not in filtered_ids()
            )
        )
        assert "epic:alpha-1" in filtered_ids()
        assert "proposal:proposal-1" not in filtered_ids()
        assert "archive:" not in " ".join(filtered_ids())
        assert len(load_calls) == baseline_loads
        status = bar.query_one("#plan-filter-status", Static)
        assert "1 match" in status.content.plain
        assert "exact" in status.content.plain
        list_status = pane.query_one("#plans-status", Static).content.plain
        assert "0/1 proposals" in list_status
        assert "0/1 epics" in list_status
        assert "1/2 phases" in list_status
        assert "0/1 archived" in list_status

        await page.press("enter")
        await page.wait_for(lambda _state: not bar.display)
        assert pane.filters.text == ("load",)
        assert page.app.focused is pane.query_one("#plans-list", OptionList)
        assert "load" in pane.query_one("#plans-info", Static).content.plain

        # The registry-backed f action opens the same prefilled bar. Pane
        # actions stay dormant while its editor owns focus.
        edit_bead = Mock()
        launch_epic = Mock()
        cycle_status = Mock()
        monkeypatch.setattr(page.app, "action_plans_edit_bead", edit_bead)
        monkeypatch.setattr(page.app, "action_plans_launch_epic", launch_epic)
        monkeypatch.setattr(page.app, "action_plans_cycle_status", cycle_status)
        await page.press("f")
        await page.wait_for(lambda _state: bar.display)
        assert editor.text == "load"
        await page.press("e", "w", "s")
        assert editor.text == "loadews"
        assert edit_bead.call_count == 0
        assert launch_epic.call_count == 0
        assert cycle_status.call_count == 0
        await page.press("escape")
        await page.wait_for(lambda _state: not bar.display)
        assert pane.filters.text == ("load",)

        # A new snapshot gets a fresh index and the in-progress filter is
        # immediately re-applied when the worker result lands.
        await page.press("slash")
        current_snapshot[0] = refreshed
        pane._request_load(force=True)
        await page.wait_for(lambda _state: pane.snapshot is refreshed)
        assert pane._live_filter_values is not None
        assert pane._live_filter_values.text == ("load",)
        assert "phase:alpha-1.1" in filtered_ids()
        assert pane.selected_row() is not None
        await page.press("escape")

        # Slash is still intentionally inert on Bugs.
        await page.press("3", "slash")
        await page.expect_state("artifacts_subtab", "bugs")
        await page.pause()
        assert bar.display is False
        assert page.state["modal"] is None


async def test_plans_filter_escape_restores_expansion_and_selection(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    snapshot = _snapshot(tmp_path)
    monkeypatch.setattr(
        "sase.ace.tui.actions.artifacts._collect_artifacts_project_choices",
        _choices,
    )
    monkeypatch.setattr(
        "sase.ace.tui.widgets.artifacts.plans_pane.load_plans_snapshot",
        lambda _project, **_kwargs: snapshot,
    )

    async with AcePage(initial_tab="changespecs") as page:
        await page.press("[")
        pane = page.query_one_widget("#artifacts-plans-pane", ArtifactsPlansPane)
        await page.wait_for(lambda _state: pane.snapshot is snapshot)
        await page.press("j", "l", "j")
        assert pane.selected_row() is not None
        assert pane.selected_row().row_id == "phase:alpha-1.1"  # type: ignore[union-attr]
        expanded = set(pane._expanded_epics)

        await page.press("slash", "a", "r", "c", "h", "i", "v", "e")
        await page.wait_for(
            lambda _state: (
                pane.selected_row() is not None
                and pane.selected_row().kind == "archive"
            )
        )
        await page.press("escape")
        await page.wait_for(
            lambda _state: (
                pane.selected_row() is not None
                and pane.selected_row().row_id == "phase:alpha-1.1"
            )
        )

        assert pane.filters.is_empty
        assert pane._expanded_epics == expanded


async def test_plans_filter_rejects_invalid_submit(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    snapshot = _snapshot(tmp_path)
    monkeypatch.setattr(
        "sase.ace.tui.actions.artifacts._collect_artifacts_project_choices",
        _choices,
    )
    monkeypatch.setattr(
        "sase.ace.tui.widgets.artifacts.plans_pane.load_plans_snapshot",
        lambda _project, **_kwargs: snapshot,
    )

    async with AcePage(
        initial_tab="changespecs",
        notifications=True,
    ) as page:
        await page.press("[")
        pane = page.query_one_widget("#artifacts-plans-pane", ArtifactsPlansPane)
        await page.wait_for(lambda _state: pane.snapshot is snapshot)
        bar = pane.query_one(PlanFilterBar)

        await page.press("slash", "s", "t", "a", "t", "u", "s", "colon", "enter")
        await page.pause()

        assert bar.display is True
        assert bar.query_one("#plan-filter-status", Static).has_class("error")
        assert pane.filters.is_empty
