"""ACE PNG visual snapshot coverage for Artifacts → Plans."""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import pytest
from textual.containers import VerticalScroll
from textual.widgets import OptionList, Static

from sase.ace.testing import AcePage
from sase.ace.tui.widgets.artifacts.plan_filter_bar import PlanFilterBar
from sase.ace.tui.widgets.artifacts.plans_data import (
    LinkedPlanDocument,
    PlansSnapshot,
    ProjectIssue,
)
from sase.ace.tui.widgets.artifacts.plans_pane import ArtifactsPlansPane
from sase.ace.tui.widgets.single_line_vim_text_area import SingleLineVimTextArea
from sase.bead.model import PhaseSize
from sase.plan_search.filter_query import parse_plan_filter_query
from tests.ace.tui._artifacts_plans_helpers import _choices, _snapshot
from tests.ace.tui.visual._ace_agents_png_snapshot_helpers import (
    assert_page_svg_contains,
)
from tests.ace.tui.visual._ace_png_snapshot_helpers import (
    changespecs,
    patch_startup_loaders,
    wait_for_startup,
    wait_for_svg_contains,
    wait_for_visual_idle,
)
from tests.ace.tui.visual.png_diff import AcePngSnapshotFixture

pytestmark = pytest.mark.visual


def _visual_snapshot(tmp_path: Path) -> PlansSnapshot:
    snapshot = _snapshot(tmp_path)
    epic = snapshot.epics[0].issue
    phases = snapshot.phases_by_epic[("alpha", epic.id)]
    large_phase = replace(
        phases[1].issue,
        id="alpha-1.3",
        title="Polish visual states",
        size=PhaseSize.LARGE,
        dependencies=[],
    )
    xsmall_phase = replace(
        phases[0].issue,
        id="alpha-1.0",
        title="Sketch the smallest state",
        size=PhaseSize.XSMALL,
        dependencies=[],
    )
    xlarge_phase = replace(
        phases[1].issue,
        id="alpha-1.5",
        title="Reframe the largest state",
        size=PhaseSize.XLARGE,
        dependencies=[],
    )
    return replace(
        snapshot,
        proposals=(
            replace(
                snapshot.proposals[0],
                plan_path="/workspace/alpha--plans/202607/ship_plan_browser.md",
            ),
        ),
        phases_by_epic={
            ("alpha", epic.id): (
                ProjectIssue("alpha", xsmall_phase),
                *phases,
                ProjectIssue("alpha", large_phase),
                ProjectIssue("alpha", xlarge_phase),
            )
        },
    )


def _linked_visual_snapshot(tmp_path: Path) -> PlansSnapshot:
    snapshot = _visual_snapshot(tmp_path)
    epic = replace(snapshot.epics[0].issue, design="202607/ship_plan_browser.md")
    document = LinkedPlanDocument(
        reference=epic.design,
        path="/workspace/alpha--plans/202607/ship_plan_browser.md",
        content="# Ship the plan browser\n\nLinked plan content.\n",
        frontmatter={},
        body="# Ship the plan browser\n\nLinked plan content.\n",
        error=None,
        signature=(1, 1, 1, 1),
    )
    return replace(
        snapshot,
        epics=(replace(snapshot.epics[0], issue=epic),),
        linked_plan_documents={("alpha", epic.id): document},
    )


async def _open_plans(
    page: AcePage,
    snapshot: PlansSnapshot,
) -> tuple[ArtifactsPlansPane, PlanFilterBar]:
    await wait_for_startup(page)
    await page.press("2")
    await page.expect_state("artifacts_subtab", "plans")
    pane = page.query_one_widget("#artifacts-plans-pane", ArtifactsPlansPane)
    await page.wait_for(lambda _state: pane.snapshot is snapshot)
    return pane, pane.query_one(PlanFilterBar)


async def _commit_plan_filter_query(
    page: AcePage,
    pane: ArtifactsPlansPane,
    bar: PlanFilterBar,
    query: str,
) -> None:
    values = parse_plan_filter_query(query)
    await page.press("slash")
    await page.wait_for(lambda _state: bar.display)
    bar.query_one("#plan-filter-input", SingleLineVimTextArea).load_text(query)
    await page.wait_for(lambda _state: pane._live_filter_values == values)
    await page.press("enter")
    await page.wait_for(
        lambda _state: (
            not bar.display
            and pane.filters == values
            and pane.query_one("#plans-list", OptionList).has_focus
        )
    )


async def test_artifacts_plans_populated_png_snapshot(
    ace_png_visual: AcePngSnapshotFixture,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    patch_startup_loaders(monkeypatch)
    snapshot = _linked_visual_snapshot(tmp_path)
    monkeypatch.setattr(
        "sase.ace.tui.actions.artifacts._collect_artifacts_project_choices",
        _choices,
    )
    monkeypatch.setattr(
        "sase.ace.tui.widgets.artifacts.plans_pane.load_plans_snapshot",
        lambda _project, **_kwargs: snapshot,
    )

    async with AcePage(query='"visual"', changespecs=changespecs()) as page:
        await wait_for_startup(page)
        await page.press("2")
        await page.expect_state("artifacts_subtab", "plans")
        pane = page.query_one_widget("#artifacts-plans-pane", ArtifactsPlansPane)
        await page.wait_for(lambda _state: pane.snapshot is snapshot)
        await page.press("j", "l", "j")
        await page.wait_for(
            lambda _state: (
                (row := pane.selected_row()) is not None
                and row.row_id == "phase:alpha-1.0"
            )
        )
        await page.wait_for(
            lambda _state: (
                pane._detail_debouncer is None or not pane._detail_debouncer.is_pending
            )
        )
        pane._update_detail()
        detail_scroll = pane.query_one("#plans-detail-scroll", VerticalScroll)
        await page.wait_for(lambda _state: detail_scroll.max_scroll_y > 0)
        detail_scroll.scroll_to(
            y=detail_scroll.max_scroll_y,
            animate=False,
            immediate=True,
        )
        page.app.refresh(layout=True)
        await page.app.wait_for_refresh()
        await wait_for_svg_contains(page, "Linked plan content.")
        await wait_for_visual_idle(page)
        for label in ("xsmall", "small", "medium", "large", "xlarge"):
            assert_page_svg_contains(page, label)
        assert_page_svg_contains(page, "Size")

        ace_png_visual.assert_page_png(
            page,
            "artifacts_plans_populated_120x40",
            title="ACE Artifacts - Plans populated",
        )


async def test_plans_filter_bar_prefilled_png_snapshot(
    ace_png_visual: AcePngSnapshotFixture,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    patch_startup_loaders(monkeypatch)
    snapshot = _visual_snapshot(tmp_path)
    monkeypatch.setattr(
        "sase.ace.tui.actions.artifacts._collect_artifacts_project_choices",
        _choices,
    )
    monkeypatch.setattr(
        "sase.ace.tui.widgets.artifacts.plans_pane.load_plans_snapshot",
        lambda _project, **_kwargs: snapshot,
    )

    async with AcePage(query='"visual"', changespecs=changespecs()) as page:
        pane, bar = await _open_plans(page, snapshot)
        query = "kind:phase load"
        await _commit_plan_filter_query(page, pane, bar, query)
        await page.press("slash")
        editor = bar.query_one("#plan-filter-input", SingleLineVimTextArea)
        await page.wait_for(lambda _state: bar.display and editor.text == query)
        await wait_for_svg_contains(page, "1 match")
        await wait_for_visual_idle(page)

        ace_png_visual.assert_page_png(
            page,
            "artifacts_plans_filter_bar_prefilled_120x40",
            title="ACE Artifacts Plans prefilled filter bar",
        )


async def test_plans_filter_completion_png_snapshot(
    ace_png_visual: AcePngSnapshotFixture,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    patch_startup_loaders(monkeypatch)
    snapshot = _visual_snapshot(tmp_path)
    monkeypatch.setattr(
        "sase.ace.tui.actions.artifacts._collect_artifacts_project_choices",
        _choices,
    )
    monkeypatch.setattr(
        "sase.ace.tui.widgets.artifacts.plans_pane.load_plans_snapshot",
        lambda _project, **_kwargs: snapshot,
    )

    async with AcePage(query='"visual"', changespecs=changespecs()) as page:
        pane, bar = await _open_plans(page, snapshot)
        pane.show_filters()
        bar.open("status:")
        completion = bar.query_one("#plan-filter-completion", OptionList)
        await page.wait_for(
            lambda _state: completion.display and completion.option_count == 8
        )
        await wait_for_svg_contains(page, "in_progress")
        await wait_for_visual_idle(page)

        ace_png_visual.assert_page_png(
            page,
            "artifacts_plans_filter_completion_120x40",
            title="ACE Artifacts Plans status completion",
        )


async def test_plans_narrowed_filter_chips_png_snapshot(
    ace_png_visual: AcePngSnapshotFixture,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    patch_startup_loaders(monkeypatch)
    snapshot = _visual_snapshot(tmp_path)
    monkeypatch.setattr(
        "sase.ace.tui.actions.artifacts._collect_artifacts_project_choices",
        _choices,
    )
    monkeypatch.setattr(
        "sase.ace.tui.widgets.artifacts.plans_pane.load_plans_snapshot",
        lambda _project, **_kwargs: snapshot,
    )

    async with AcePage(query='"visual"', changespecs=changespecs()) as page:
        pane, bar = await _open_plans(page, snapshot)
        await _commit_plan_filter_query(page, pane, bar, "load")
        options = pane.query_one("#plans-list", OptionList)

        def option_ids() -> set[str]:
            return {
                options.get_option_at_index(index).id or ""
                for index in range(options.option_count)
            }

        await page.wait_for(
            lambda _state: (
                "epic:alpha-1" in option_ids()
                and "phase:alpha-1.1" in option_ids()
                and "phase:alpha-1.2" not in option_ids()
            )
        )
        status = pane.query_one("#plans-status", Static)
        await page.wait_for(
            lambda _state: (
                "0/1 proposals" in status.content.plain
                and "1/5 phases" in status.content.plain
                and "load" in pane.query_one("#plans-info", Static).content.plain
            )
        )
        await wait_for_svg_contains(page, "Load plans")
        await wait_for_visual_idle(page)

        ace_png_visual.assert_page_png(
            page,
            "artifacts_plans_narrowed_filter_chips_120x40",
            title="ACE Artifacts Plans narrowed filter chips",
        )


async def test_plans_filter_parse_error_png_snapshot(
    ace_png_visual: AcePngSnapshotFixture,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    patch_startup_loaders(monkeypatch)
    snapshot = _visual_snapshot(tmp_path)
    monkeypatch.setattr(
        "sase.ace.tui.actions.artifacts._collect_artifacts_project_choices",
        _choices,
    )
    monkeypatch.setattr(
        "sase.ace.tui.widgets.artifacts.plans_pane.load_plans_snapshot",
        lambda _project, **_kwargs: snapshot,
    )

    async with AcePage(query='"visual"', changespecs=changespecs()) as page:
        _pane, bar = await _open_plans(page, snapshot)
        await page.press("slash")
        await page.wait_for(lambda _state: bar.display)
        bar.query_one("#plan-filter-input", SingleLineVimTextArea).load_text("status:")
        await page.wait_for(
            lambda _state: bar.query_one("#plan-filter-status").has_class("error")
        )
        await page.press("escape")
        await page.wait_for(
            lambda _state: not bar.query_one("#plan-filter-completion").display
        )
        await wait_for_svg_contains(page, "status: requires a value")
        await wait_for_visual_idle(page)

        ace_png_visual.assert_page_png(
            page,
            "artifacts_plans_filter_parse_error_120x40",
            title="ACE Artifacts Plans filter parse error",
        )
