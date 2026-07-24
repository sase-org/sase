"""Navigation and tracked-action coverage for the Artifacts Plans pane."""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path
from unittest.mock import Mock

import pytest
from textual.widgets import Input, OptionList

from sase.ace.testing import AcePage
from sase.ace.tui.widgets.artifacts.plans_data import PlansSnapshot
from sase.ace.tui.widgets.artifacts.plans_pane import ArtifactsPlansPane
from sase.bead.model import Issue, Status
from tests.ace.tui._artifacts_plans_helpers import (
    _all_choices,
    _all_projects_snapshot,
    _choices,
    _snapshot,
)


async def test_plans_pane_renders_groups_and_expands_phase_tree(
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
        await page.press("2")
        await page.expect_state("artifacts_subtab", "plans")
        pane = page.query_one_widget("#artifacts-plans-pane", ArtifactsPlansPane)
        await page.wait_for(lambda _state: pane.snapshot is snapshot)

        assert pane.selected_row() is not None
        assert pane.selected_row().kind == "proposal"  # type: ignore[union-attr]
        assert page.app.check_action("change_status", ()) is False
        assert page.app.check_action("plans_cycle_status", ()) is True

        await page.press("j")
        assert pane.selected_row() is not None
        assert pane.selected_row().kind == "epic"  # type: ignore[union-attr]
        await page.press("l")
        option_ids = {
            pane.query_one("#plans-list", OptionList).get_option_at_index(index).id
            for index in range(pane.query_one("#plans-list", OptionList).option_count)
        }
        assert "phase:alpha-1.1" in option_ids
        assert "phase:alpha-1.2" in option_ids

        await page.press("j")
        assert pane.selected_row() is not None
        assert pane.selected_row().row_id == "phase:alpha-1.1"  # type: ignore[union-attr]
        await page.press("enter")
        await page.expect_modal("PreviewPanelModal")


async def test_proposal_keys_reuse_approval_flow(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    snapshot = _snapshot(tmp_path)
    handle = Mock(return_value=True)
    monkeypatch.setattr(
        "sase.ace.tui.actions.artifacts._collect_artifacts_project_choices",
        _choices,
    )
    monkeypatch.setattr(
        "sase.ace.tui.widgets.artifacts.plans_pane.load_plans_snapshot",
        lambda _project, **_kwargs: snapshot,
    )
    monkeypatch.setattr(
        "sase.ace.tui.actions.agents._notification_modals.handle_plan_approval",
        handle,
    )

    async with AcePage(initial_tab="changespecs") as page:
        await page.press("2")
        pane = page.query_one_widget("#artifacts-plans-pane", ArtifactsPlansPane)
        await page.wait_for(lambda _state: pane.snapshot is snapshot)

        await page.press("A")
        await page.press("X")

    assert handle.call_count == 2
    assert all(call.args[1].id == "proposal-1" for call in handle.call_args_list)


async def test_status_change_runs_as_tracked_task(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    snapshot = _snapshot(tmp_path)
    updates: list[tuple[str, str, dict[str, str]]] = []
    monkeypatch.setattr(
        "sase.ace.tui.actions.artifacts._collect_artifacts_project_choices",
        _choices,
    )
    monkeypatch.setattr(
        "sase.ace.tui.widgets.artifacts.plans_pane.load_plans_snapshot",
        lambda _project, **_kwargs: snapshot,
    )

    def update(project: str, issue_id: str, fields: dict[str, str]) -> Issue:
        updates.append((project, issue_id, fields))
        return snapshot.epics[0].issue

    monkeypatch.setattr(
        "sase.ace.tui.actions.artifacts_plans._update_scoped_bead",
        update,
    )

    async with AcePage(initial_tab="changespecs") as page:
        await page.press("2")
        pane = page.query_one_widget("#artifacts-plans-pane", ArtifactsPlansPane)
        await page.wait_for(lambda _state: pane.snapshot is snapshot)
        await page.press("j", "s")
        await page.wait_for(lambda _state: page.app._task_queue.running_count == 0)

        tasks = page.app._task_queue.get_all()
        assert tasks[0].task_type == "bead status"
        assert tasks[0].status == "success"

    assert updates == [("alpha", "alpha-1", {"status": "in_progress"})]


async def test_status_cycle_from_claimed_takes_bead_over(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    snapshot = _snapshot(tmp_path)
    claimed_epic = replace(snapshot.epics[0].issue, status=Status.CLAIMED)
    snapshot = replace(
        snapshot,
        epics=(replace(snapshot.epics[0], issue=claimed_epic),),
    )
    updates: list[tuple[str, str, dict[str, str]]] = []
    monkeypatch.setattr(
        "sase.ace.tui.actions.artifacts._collect_artifacts_project_choices",
        _choices,
    )
    monkeypatch.setattr(
        "sase.ace.tui.widgets.artifacts.plans_pane.load_plans_snapshot",
        lambda _project, **_kwargs: snapshot,
    )

    def update(project: str, issue_id: str, fields: dict[str, str]) -> Issue:
        updates.append((project, issue_id, fields))
        return claimed_epic

    monkeypatch.setattr(
        "sase.ace.tui.actions.artifacts_plans._update_scoped_bead",
        update,
    )

    async with AcePage(initial_tab="changespecs") as page:
        await page.press("2")
        pane = page.query_one_widget("#artifacts-plans-pane", ArtifactsPlansPane)
        await page.wait_for(lambda _state: pane.snapshot is snapshot)
        await page.press("j", "s")
        await page.wait_for(lambda _state: page.app._task_queue.running_count == 0)

    assert updates == [("alpha", "alpha-1", {"status": "in_progress"})]


async def test_default_scope_loads_all_projects_and_namespaces_rows(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    snapshot = _all_projects_snapshot(tmp_path)
    loaded_scopes: list[str | None] = []
    monkeypatch.setattr(
        "sase.ace.tui.actions.artifacts._collect_artifacts_project_choices",
        _all_choices,
    )

    def load(project: str | None, **_kwargs: object) -> PlansSnapshot:
        loaded_scopes.append(project)
        return snapshot

    monkeypatch.setattr(
        "sase.ace.tui.widgets.artifacts.plans_pane.load_plans_snapshot",
        load,
    )

    async with AcePage(initial_tab="changespecs") as page:
        await page.press("2")
        pane = page.query_one_widget("#artifacts-plans-pane", ArtifactsPlansPane)
        await page.wait_for(lambda _state: pane.snapshot is snapshot)

        assert loaded_scopes[0] is None
        assert pane.project_scope is None
        assert "All projects" in pane._scope_text().plain
        assert pane.selected_row() is not None
        assert pane.selected_row().project == "beta"  # type: ignore[union-attr]
        option_ids = {
            pane.query_one("#plans-list", OptionList).get_option_at_index(index).id
            for index in range(pane.query_one("#plans-list", OptionList).option_count)
        }
        assert "proposal:beta:proposal-1" in option_ids
        assert "epic:beta:alpha-1" in option_ids


async def test_picker_round_trip_back_to_all_projects(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    all_snapshot = _all_projects_snapshot(tmp_path)
    monkeypatch.setattr(
        "sase.ace.tui.actions.artifacts._collect_artifacts_project_choices",
        _all_choices,
    )

    def load(project: str | None, **_kwargs: object) -> PlansSnapshot:
        if project is None:
            return all_snapshot
        return replace(
            all_snapshot,
            project=project,
            projects=(project,),
        )

    monkeypatch.setattr(
        "sase.ace.tui.widgets.artifacts.plans_pane.load_plans_snapshot",
        load,
    )

    async with AcePage(initial_tab="changespecs") as page:
        await page.press("2")
        pane = page.query_one_widget("#artifacts-plans-pane", ArtifactsPlansPane)
        await page.wait_for(
            lambda _state: (
                pane.snapshot is not None
                and pane.snapshot.project is None
                and page.app._artifacts_project_choices is not None
            )
        )

        page.app._set_artifacts_project_scope("beta", picked=True)
        await page.wait_for(
            lambda _state: pane.snapshot is not None and pane.snapshot.project == "beta"
        )
        await page.press("p")
        await page.expect_modal("InventoryProjectPicker")
        await page.press("k", "k", "enter")
        await page.wait_for(
            lambda _state: pane.snapshot is not None and pane.snapshot.project is None
        )

        assert pane.project_scope is None
        assert "All projects" in pane._scope_text().plain


async def test_all_project_bead_actions_route_to_selected_row_project(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    snapshot = _all_projects_snapshot(tmp_path)
    monkeypatch.setattr(
        "sase.ace.tui.actions.artifacts._collect_artifacts_project_choices",
        _all_choices,
    )
    monkeypatch.setattr(
        "sase.ace.tui.widgets.artifacts.plans_pane.load_plans_snapshot",
        lambda _project, **_kwargs: snapshot,
    )

    async with AcePage(initial_tab="changespecs") as page:
        await page.press("2")
        pane = page.query_one_widget("#artifacts-plans-pane", ArtifactsPlansPane)
        await page.wait_for(lambda _state: pane.snapshot is snapshot)
        await page.press("j")
        row = pane.selected_row()
        assert row is not None and row.issue is not None
        assert row.project == "beta"

        update = Mock()
        monkeypatch.setattr(page.app, "_submit_plans_bead_update", update)
        page.app.action_plans_cycle_status()
        assert update.call_args.args[1:3] == ("beta", row.issue)

        page.app.action_plans_edit_bead()
        await page.expect_modal("BeadEditModal")
        await page.pause()
        page.app.screen.query_one(
            "#bead-edit-title-input", Input
        ).value = f"{row.issue.title} updated"
        await page.press("ctrl+s")
        await page.pause()
        assert update.call_args.args[1:3] == ("beta", row.issue)

        launch = Mock()
        monkeypatch.setattr(page.app, "_submit_plans_epic_launch", launch)
        page.app.action_plans_launch_epic()
        await page.expect_modal("ConfirmActionModal")
        await page.press("y")
        await page.pause()
        assert launch.call_args.args[1:3] == ("beta", row.issue)

        tracked = Mock()
        monkeypatch.setattr(page.app, "_submit_tracked_task", tracked)
        page.app.action_plans_open_bug()
        assert tracked.call_args.args[2] == str(tmp_path / "beta-workspace")
        assert tracked.call_args.kwargs["dedup_key"] == "plans:bug:beta:42"
