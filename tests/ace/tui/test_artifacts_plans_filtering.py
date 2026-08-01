"""Live filter integration coverage for the Artifacts Plans pane."""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path
from threading import Event
from unittest.mock import Mock

import pytest
from textual.widgets import OptionList, Static

from sase.ace.testing import AcePage
from sase.ace.tui.widgets.artifacts.plan_filter_bar import PlanFilterBar
from sase.ace.tui.widgets.artifacts import plans_data
from sase.ace.tui.widgets.artifacts.plans_data import (
    PlansSnapshot,
    ProjectArchive,
    ProjectIssue,
)
from sase.ace.tui.widgets.artifacts.plans_deep_archive import (
    DeepArchiveRequest,
    DeepArchiveResult,
    merge_archive_matches,
)
from sase.ace.tui.widgets.artifacts.plans_pane import ArtifactsPlansPane
from sase.ace.tui.widgets.artifacts.plans_filtering import (
    build_plan_filter_index,
    compile_plan_matcher,
)
from sase.ace.tui.widgets.single_line_vim_text_area import SingleLineVimTextArea
from sase.plan_search.filter_query import parse_plan_filter_query

from ._artifacts_plans_helpers import _choices, _snapshot


def _deep_archive(
    snapshot: PlansSnapshot,
    tmp_path: Path,
    *,
    name: str,
    title: str,
    created_at: str,
) -> ProjectArchive:
    preview = snapshot.archive[0]
    plan = replace(
        preview.match.plan,
        path=str(tmp_path / "202606" / f"{name}.md"),
        relpath=f"202606/{name}.md",
        name=name,
        title=title,
        created_at=created_at,
        body=f"# {title}",
    )
    return ProjectArchive(
        preview.project,
        replace(preview.match, plan=plan),
    )


def test_document_kind_facet_matches_role_and_archive_category(
    tmp_path: Path,
) -> None:
    snapshot = _snapshot(tmp_path)
    designs_archive = replace(
        snapshot.archive[0],
        role="designs",
        match=replace(
            snapshot.archive[0].match,
            plan=replace(
                snapshot.archive[0].match.plan,
                kind="designs",
                path=str(tmp_path / "designs" / "202607" / "document.md"),
            ),
        ),
    )
    snapshot = replace(
        snapshot,
        plans_roots={
            "alpha": {
                "plans": str(tmp_path / "plans"),
                "designs": str(tmp_path / "designs"),
            }
        },
        archive=(*snapshot.archive, designs_archive),
    )
    index = build_plan_filter_index(snapshot)

    designs = compile_plan_matcher(parse_plan_filter_query("kind:designs"))
    all_archive = compile_plan_matcher(parse_plan_filter_query("kind:archive"))

    assert [record.kind for record in index if designs(record)] == ["archive"]
    assert sum(all_archive(record) for record in index) == 2


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
        await page.press("5")
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
        assert "0/2 tasks" in list_status
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
        await page.press("5")
        pane = page.query_one_widget("#artifacts-plans-pane", ArtifactsPlansPane)
        await page.wait_for(lambda _state: pane.snapshot is snapshot)
        await page.press("j", "j", "j")
        page.app.action_plans_expand()
        await page.press("j")
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
        await page.press("5")
        pane = page.query_one_widget("#artifacts-plans-pane", ArtifactsPlansPane)
        await page.wait_for(lambda _state: pane.snapshot is snapshot)
        bar = pane.query_one(PlanFilterBar)

        await page.press(
            "slash",
            "s",
            "t",
            "a",
            "t",
            "u",
            "s",
            "colon",
            "enter",
        )
        await page.pause()

        assert bar.display is True
        assert bar.query_one("#plan-filter-status", Static).has_class("error")
        assert pane.filters.is_empty


async def test_plans_negative_filters_preserve_tree_counts_and_submit(
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
        await page.press("5")
        pane = page.query_one_widget("#artifacts-plans-pane", ArtifactsPlansPane)
        await page.wait_for(lambda _state: pane.snapshot is snapshot)
        await page.press("slash")
        bar = pane.query_one(PlanFilterBar)
        editor = bar.query_one("#plan-filter-input", SingleLineVimTextArea)
        query = "-kind:archive -status:blocked -project:beta -rollout"
        editor.load_text(query)
        editor.cursor_position = len(query)

        def option_ids() -> set[str]:
            options = pane.query_one("#plans-list", OptionList)
            return {
                options.get_option_at_index(index).id or ""
                for index in range(options.option_count)
            }

        await page.wait_for(
            lambda _state: (
                "proposal:proposal-1" in option_ids()
                and "epic:alpha-1" in option_ids()
                and "phase:alpha-1.1" in option_ids()
                and "phase:alpha-1.2" not in option_ids()
                and not any(value.startswith("archive:") for value in option_ids())
            )
        )
        assert "5 matches" in bar.query_one("#plan-filter-status", Static).content.plain
        list_status = pane.query_one("#plans-status", Static).content.plain
        assert "1/1 proposals" in list_status
        assert "2/2 tasks" in list_status
        assert "1/1 epics" in list_status
        assert "1/2 phases" in list_status
        assert "0/1 archived" in list_status

        await page.press("enter")
        await page.wait_for(lambda _state: not bar.display)
        assert pane.filters.excluded_kinds == ("archive",)
        assert pane.filters.excluded_statuses == ("blocked",)
        assert pane.filters.excluded_projects == ("beta",)
        assert pane.filters.excluded_text == ("rollout",)
        assert "-kind:archive" in pane.query_one("#plans-info", Static).content.plain


def test_deep_archive_trigger_and_capped_coverage_are_honest(
    tmp_path: Path,
) -> None:
    snapshot = replace(_snapshot(tmp_path), archive_truncated=True)
    pane = ArtifactsPlansPane()
    pane.project_scope = "alpha"
    pane._snapshot = snapshot
    pane._filter_session_open = True

    values = parse_plan_filter_query("needle")
    request = pane._deep_archive_request_for(values)
    assert request is not None
    assert (
        pane._deep_archive_request_for(parse_plan_filter_query("kind:proposal needle"))
        is None
    )
    assert (
        pane._deep_archive_request_for(parse_plan_filter_query("-kind:archive")) is None
    )
    assert (
        pane._deep_archive_request_for(parse_plan_filter_query("-kind:proposal"))
        is not None
    )

    pane._deep_archive_cache[request] = DeepArchiveResult(
        request=request,
        archive=(),
        scanned_count=500,
        capped=True,
        errors=(),
    )
    assert pane._filter_coverage(values) == (False, "newest 500 searched")

    pane._snapshot = replace(snapshot, archive_truncated=False)
    assert pane._deep_archive_request_for(values) is None


def test_deep_archive_merge_deduplicates_and_preserves_recency(
    tmp_path: Path,
) -> None:
    snapshot = _snapshot(tmp_path)
    preview = snapshot.archive[0]
    duplicate = ProjectArchive(
        preview.project,
        replace(
            preview.match,
            plan=replace(preview.match.plan, title="Deep copy wins"),
        ),
    )
    newest = _deep_archive(
        snapshot,
        tmp_path,
        name="newest",
        title="Newest",
        created_at="2026-07-05 10:00:00",
    )
    oldest = _deep_archive(
        snapshot,
        tmp_path,
        name="oldest",
        title="Oldest",
        created_at="2026-07-03 10:00:00",
    )

    merged = merge_archive_matches((preview, oldest), (duplicate, newest))

    assert [item.match.plan.title for item in merged] == [
        "Newest",
        "Deep copy wins",
        "Oldest",
    ]


async def test_deep_archive_typing_burst_fetches_final_query_once_and_becomes_exact(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    snapshot = replace(_snapshot(tmp_path), archive_truncated=True)
    older_match = _deep_archive(
        snapshot,
        tmp_path,
        name="needle",
        title="Needle in the deep archive",
        created_at="2026-06-01 10:00:00",
    )
    requests: list[DeepArchiveRequest] = []
    monkeypatch.setattr(
        "sase.ace.tui.actions.artifacts._collect_artifacts_project_choices",
        _choices,
    )
    monkeypatch.setattr(
        "sase.ace.tui.widgets.artifacts.plans_pane.load_plans_snapshot",
        lambda _project, **_kwargs: snapshot,
    )

    def load_deep(
        _snapshot: PlansSnapshot,
        request: DeepArchiveRequest,
    ) -> DeepArchiveResult:
        requests.append(request)
        return DeepArchiveResult(
            request=request,
            archive=(older_match,),
            scanned_count=2,
            capped=False,
            errors=(),
        )

    monkeypatch.setattr(
        "sase.ace.tui.widgets.artifacts.plans_filter_session.load_deep_archive_result",
        load_deep,
    )

    async with AcePage(initial_tab="changespecs") as page:
        await page.press("5")
        pane = page.query_one_widget("#artifacts-plans-pane", ArtifactsPlansPane)
        await page.wait_for(lambda _state: pane.snapshot is snapshot)
        bar = pane.query_one(PlanFilterBar)

        await page.press("slash", "n", "e", "e", "d", "l", "e")
        final_values = parse_plan_filter_query("needle")
        final_request = pane._deep_archive_request_for(final_values)
        assert final_request is not None
        await page.wait_for(lambda _state: final_request in requests)

        def option_ids() -> set[str]:
            options = pane.query_one("#plans-list", OptionList)
            return {
                options.get_option_at_index(index).id or ""
                for index in range(options.option_count)
            }

        deep_option_id = f"archive:{older_match.match.plan.path}"
        await page.wait_for(lambda _state: deep_option_id in option_ids())
        status = bar.query_one("#plan-filter-status", Static).content.plain
        assert "1 match" in status
        assert "exact" in status
        assert "1/2 archived" in pane.query_one("#plans-status", Static).content.plain
        assert requests.count(final_request) == 1
        assert all(
            request.project_roots == (("alpha", "plans", str(tmp_path)),)
            for request in requests
        )


async def test_escape_discards_in_flight_deep_archive_result(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    snapshot = replace(_snapshot(tmp_path), archive_truncated=True)
    stale_match = _deep_archive(
        snapshot,
        tmp_path,
        name="stale",
        title="Needle from a stale request",
        created_at="2026-06-01 10:00:00",
    )
    started = Event()
    release = Event()
    monkeypatch.setattr(
        "sase.ace.tui.actions.artifacts._collect_artifacts_project_choices",
        _choices,
    )
    monkeypatch.setattr(
        "sase.ace.tui.widgets.artifacts.plans_pane.load_plans_snapshot",
        lambda _project, **_kwargs: snapshot,
    )

    def load_deep(
        _roots: tuple[tuple[str, str], ...],
    ) -> plans_data._DeepArchiveFetch:
        started.set()
        assert release.wait(timeout=5)
        return plans_data._DeepArchiveFetch(
            archive=(stale_match,),
            scanned_count=1,
            capped=False,
            errors={},
        )

    monkeypatch.setattr(
        "sase.ace.tui.widgets.artifacts.plans_deep_archive.load_deep_plan_archive",
        load_deep,
    )

    async with AcePage(initial_tab="changespecs") as page:
        await page.press("5")
        pane = page.query_one_widget("#artifacts-plans-pane", ArtifactsPlansPane)
        await page.wait_for(lambda _state: pane.snapshot is snapshot)
        bar = pane.query_one(PlanFilterBar)

        await page.press("slash", "n", "e", "e", "d", "l", "e")
        await page.wait_for(lambda _state: started.is_set())
        await page.press("escape")
        await page.wait_for(lambda _state: not bar.display)
        release.set()
        await page.wait_for(lambda _state: pane._deep_archive_worker is None)

        assert pane.filters.is_empty
        assert pane._deep_archive_cache == {}
        assert all(
            row.archive is None or row.archive.plan.path != stale_match.match.plan.path
            for row in pane._rows.values()
        )
