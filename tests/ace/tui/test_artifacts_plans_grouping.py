"""Shared-registry grouping/fold behavior for the Artifacts Plans pane."""

from __future__ import annotations

from pathlib import Path

import pytest

from sase.ace.testing import AcePage
from sase.ace.tui.widgets.artifacts.plans_list import plan_row_target
from sase.ace.tui.widgets.artifacts.plans_pane import ArtifactsPlansPane
from tests.ace.tui._artifacts_plans_helpers import _choices, _snapshot


async def _mounted_pane(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> tuple[AcePage, ArtifactsPlansPane]:
    snapshot = _snapshot(tmp_path)
    monkeypatch.setattr(
        "sase.ace.tui.actions.artifacts._collect_artifacts_project_choices",
        _choices,
    )
    monkeypatch.setattr(
        "sase.ace.tui.widgets.artifacts.plans_pane.load_plans_snapshot",
        lambda _project, **_kwargs: snapshot,
    )
    page = AcePage(initial_tab="patches")
    await page.__aenter__()
    await page.press(page.artifacts_digit("ref:plan"))
    await page.expect_state("artifacts_subtab", "ref:plan")
    pane = page.query_one_widget("#artifacts-plans-pane", ArtifactsPlansPane)
    await page.wait_for(lambda _state: pane.snapshot is snapshot)
    return page, pane


async def test_default_mode_is_by_kind_and_cycles_through_declared_modes(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    page, pane = await _mounted_pane(monkeypatch, tmp_path)
    try:
        mode = pane._active_grouping_mode()
        assert mode is not None
        assert mode.id == "by_kind"

        assert pane.group_cycle_mode() is True
        mode = pane._active_grouping_mode()
        assert mode is not None
        assert mode.id == "by_status"

        assert pane.group_cycle_mode() is True
        mode = pane._active_grouping_mode()
        assert mode is not None
        assert mode.id == "by_project"

        assert pane.group_cycle_mode() is True
        mode = pane._active_grouping_mode()
        assert mode is not None
        assert mode.id == "by_kind"
    finally:
        await page.__aexit__(None, None, None)


async def test_collapsing_the_active_kind_group_hides_its_row(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    page, pane = await _mounted_pane(monkeypatch, tmp_path)
    try:
        assert pane.selected_row() is not None
        active_row = next(row for row in pane._rows.values() if row.kind == "active")
        active_target = plan_row_target(active_row)
        assert pane.select_entry_target(active_target)
        before = pane.entry_targets()
        assert active_target in before

        assert pane.group_fold_collapse() is True
        after_collapse = pane.entry_targets()
        assert active_target not in after_collapse
        selected = pane.selected_entry_target()
        assert selected is not None
        assert selected in after_collapse

        assert pane.group_fold_expand() is True
        after_expand = pane.entry_targets()
        assert active_target in after_expand
        assert pane.selected_entry_target() == active_target
    finally:
        await page.__aexit__(None, None, None)
