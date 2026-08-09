"""Navigation and action coverage for the document-only Plans pane."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import Mock

import pytest

from sase.ace.testing import AcePage
from sase.ace.tui.actions.artifacts_plans import ArtifactsPlansActionsMixin
from sase.ace.tui.widgets.artifacts.plans_list import build_plan_options
from sase.ace.tui.widgets.artifacts.plans_pane import ArtifactsPlansPane
from tests.ace.tui._artifacts_plans_helpers import _choices, _snapshot


def test_every_document_preview_defaults_to_rendered(tmp_path: Path) -> None:
    snapshot = _snapshot(tmp_path)
    _options, rows = build_plan_options(
        snapshot,
        project_scope="alpha",
        loading=False,
    )
    pane = ArtifactsPlansPane()
    pane._snapshot = snapshot  # noqa: SLF001

    assert {row.kind for row in rows.values()} == {"proposal", "active", "archive"}
    for row in rows.values():
        preview = pane.preview_for_row(row)
        assert preview is not None
        assert preview.default_view == "rendered"


def test_bead_only_plan_actions_are_removed() -> None:
    for name in (
        "action_plans_expand",
        "action_plans_collapse",
        "action_plans_cycle_status",
        "action_plans_edit_bead",
        "action_plans_launch_epic",
        "action_plans_open_bug",
    ):
        assert not hasattr(ArtifactsPlansActionsMixin, name)


async def test_plans_pane_navigates_three_document_sections(
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

    async with AcePage(initial_tab="patches") as page:
        await page.press("5")
        await page.expect_state("files_subtab", "plans")
        pane = page.query_one_widget("#artifacts-plans-pane", ArtifactsPlansPane)
        await page.wait_for(lambda _state: pane.snapshot is snapshot)

        assert pane.selected_row().kind == "proposal"  # type: ignore[union-attr]
        await page.press("j")
        assert pane.selected_row().kind == "active"  # type: ignore[union-attr]
        await page.press("j")
        assert pane.selected_row().kind == "archive"  # type: ignore[union-attr]
        await page.press("enter")
        await page.expect_modal("PreviewPanelModal")


async def test_proposal_actions_keep_existing_approval_flow(
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

    async with AcePage(initial_tab="patches") as page:
        await page.press("5")
        pane = page.query_one_widget("#artifacts-plans-pane", ArtifactsPlansPane)
        await page.wait_for(lambda _state: pane.snapshot is snapshot)
        page.app.action_plans_approve()

    handle.assert_called_once_with(page.app, snapshot.proposals[0].notification)
