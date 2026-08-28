"""ACE PNG visual snapshot coverage for Artifacts → Plans."""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import pytest
from textual.widgets import OptionList, Static

from sase.ace.testing import AcePage
from sase.ace.tui.widgets.artifacts.plan_filter_bar import PlanFilterBar
from sase.ace.tui.widgets.artifacts.plans_data import PlansSnapshot
from sase.ace.tui.widgets.artifacts.plans_pane import ArtifactsPlansPane
from sase.ace.tui.widgets.single_line_vim_text_area import SingleLineVimTextArea
from sase.plan_search.filter_query import parse_plan_filter_query
from tests.ace.tui._artifacts_plans_helpers import _choices, _snapshot
from tests.ace.tui.visual._ace_agents_png_snapshot_helpers import (
    assert_page_svg_contains,
)
from tests.ace.tui.visual._ace_png_snapshot_helpers import (
    patches,
    patch_startup_loaders,
    wait_for_startup,
    wait_for_svg_contains,
    wait_for_visual_idle,
)
from tests.ace.tui.visual.png_diff import AcePngSnapshotFixture

pytestmark = pytest.mark.visual


def _visual_snapshot(tmp_path: Path) -> PlansSnapshot:
    snapshot = _snapshot(tmp_path)
    active_path = "/workspace/alpha--plans/202607/active.md"
    archive_path = "/workspace/alpha--plans/202607/archive.md"
    active = snapshot.active[0]
    active_document = replace(active.document, path=active_path)
    active_owner = replace(active.owner, path=active_path)
    archive = snapshot.archive[0]
    archive_match = replace(
        archive.match,
        plan=replace(archive.match.plan, path=archive_path),
    )
    bead_plan_links = {
        key: replace(
            link,
            path=archive_path if "archive" in link.reference else active_path,
        )
        for key, link in snapshot.bead_plan_links.items()
    }
    return replace(
        snapshot,
        proposals=(
            replace(
                snapshot.proposals[0],
                plan_path="/workspace/alpha--plans/202607/ship_plan_browser.md",
            ),
        ),
        active=(replace(active, document=active_document, owner=active_owner),),
        archive=(replace(archive, match=archive_match),),
        bead_plan_links=bead_plan_links,
        linked_plan_documents=dict.fromkeys(
            snapshot.linked_plan_documents, active_document
        ),
    )


def _linked_visual_snapshot(tmp_path: Path) -> PlansSnapshot:
    return _visual_snapshot(tmp_path)


async def _open_plans(
    page: AcePage,
    snapshot: PlansSnapshot,
) -> tuple[ArtifactsPlansPane, PlanFilterBar]:
    await wait_for_startup(page)
    await page.press(page.artifacts_digit("ref:plan"))
    await page.expect_state("artifacts_subtab", "ref:plan")
    pane = page.query_one_widget("#artifacts-plans-pane", ArtifactsPlansPane)
    await page.wait_for(lambda _state: pane.snapshot is snapshot)
    await page.wait_for(
        lambda _state: getattr(pane, "_project_display_name", None) == "Alpha",
        timeout=15.0,
    )
    return pane, pane.query_one(PlanFilterBar)


async def _commit_plan_filter_query(
    page: AcePage,
    pane: ArtifactsPlansPane,
    bar: PlanFilterBar,
    query: str,
) -> None:
    values = parse_plan_filter_query(query)
    await page.press("slash")
    await page.wait_for(lambda _state: bar._editing)  # noqa: SLF001
    bar.query_one("#plan-filter-input", SingleLineVimTextArea).load_text(query)
    await page.wait_for(lambda _state: pane._live_filter_values == values)
    await page.press("enter")
    await page.wait_for(
        lambda _state: (
            not bar._editing  # noqa: SLF001
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

    async with AcePage(query='"visual"', patches=patches()) as page:
        await wait_for_startup(page)
        await page.press(page.artifacts_digit("ref:plan"))
        await page.expect_state("artifacts_subtab", "ref:plan")
        pane = page.query_one_widget("#artifacts-plans-pane", ArtifactsPlansPane)
        await page.wait_for(lambda _state: pane.snapshot is snapshot)
        await page.wait_for(
            lambda _state: getattr(pane, "_project_display_name", None) == "Alpha",
            timeout=15.0,
        )
        await page.press("j")
        await page.wait_for(
            lambda _state: (
                (row := pane.selected_row()) is not None and row.kind == "active"
            )
        )
        await page.wait_for(
            lambda _state: (
                pane._detail_debouncer is None or not pane._detail_debouncer.is_pending
            )
        )
        pane._update_detail()
        await wait_for_svg_contains(page, "Active body.")
        await wait_for_visual_idle(page)
        assert_page_svg_contains(page, "Owning bead")
        assert_page_svg_contains(page, "Design reference")

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

    async with AcePage(query='"visual"', patches=patches()) as page:
        pane, bar = await _open_plans(page, snapshot)
        query = "kind:active Active"
        await _commit_plan_filter_query(page, pane, bar, query)
        await page.press("slash")
        editor = bar.query_one("#plan-filter-input", SingleLineVimTextArea)
        await page.wait_for(
            lambda _state: bar._editing and editor.text == query  # noqa: SLF001
        )
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

    async with AcePage(query='"visual"', patches=patches()) as page:
        pane, bar = await _open_plans(page, snapshot)
        pane.show_filters()
        bar.open("status:")
        completion = bar.query_one("#plan-filter-completion", OptionList)
        await page.wait_for(
            lambda _state: completion.display and completion.option_count >= 3
        )
        completion_labels = [
            completion.get_option_at_index(index).prompt.plain
            for index in range(completion.option_count)
        ]
        assert sum(label.startswith("proposed") for label in completion_labels) == 1
        await wait_for_svg_contains(page, "wip")
        await wait_for_svg_contains(page, "done")
        await wait_for_visual_idle(page)

        ace_png_visual.assert_page_png(
            page,
            "artifacts_plans_filter_completion_120x40",
            title="ACE Artifacts Plans status completion",
        )


async def test_plans_narrowed_filter_bar_png_snapshot(
    ace_png_visual: AcePngSnapshotFixture,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """The committed query now lives only in the idle bar, not header chips."""
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

    async with AcePage(query='"visual"', patches=patches()) as page:
        pane, bar = await _open_plans(page, snapshot)
        await _commit_plan_filter_query(page, pane, bar, "Active")
        options = pane.query_one("#plans-list", OptionList)
        display = bar.query_one("#plan-filter-display", Static)

        def option_ids() -> set[str]:
            return {
                options.get_option_at_index(index).id or ""
                for index in range(options.option_count)
            }

        await page.wait_for(
            lambda _state: (
                any(value.startswith("active:") for value in option_ids())
                and not any(value.startswith("archive:") for value in option_ids())
            )
        )
        status = pane.query_one("#plans-status", Static)
        await page.wait_for(
            lambda _state: (
                "0/1 proposals" in status.content.plain
                and "1/1 active" in status.content.plain
                and display.render().plain == "Active"
            )
        )
        await wait_for_svg_contains(page, "Active rollout")
        await wait_for_visual_idle(page)

        ace_png_visual.assert_page_png(
            page,
            "artifacts_plans_narrowed_filter_bar_120x40",
            title="ACE Artifacts Plans narrowed filter bar",
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

    async with AcePage(query='"visual"', patches=patches()) as page:
        _pane, bar = await _open_plans(page, snapshot)
        await page.press("slash")
        await page.wait_for(lambda _state: bar._editing)  # noqa: SLF001
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
