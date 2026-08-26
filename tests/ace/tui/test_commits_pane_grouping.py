"""Shared-registry grouping/fold behavior for the Artifacts Stitches pane."""

from __future__ import annotations

from typing import Any

import pytest

from sase.ace.testing import AcePage
from sase.ace.tui.widgets.artifacts import CommitsPane
from sase.ace.tui.widgets.artifacts.commits_timeline import commit_row_target
from sase.ace.tui.widgets.artifacts.entry_navigation import ArtifactEntryTarget
import sase.ace.tui.widgets.artifacts.commits as commits_module
from sase.vcs_log.models import VcsLogResult
from tests.ace.tui._commits_pane_helpers import _result


async def _mounted_pane(
    monkeypatch: pytest.MonkeyPatch, result: VcsLogResult
) -> tuple[AcePage, CommitsPane]:
    def collect(**_kwargs: Any) -> VcsLogResult:
        return result

    monkeypatch.setattr(commits_module, "run_vcs_log", collect)
    page = AcePage(initial_tab="patches")
    await page.__aenter__()
    await page.press(page.artifacts_digit("stitches"))
    await page.expect_state("artifacts_subtab", "stitches")
    pane = page.query_one_widget("#artifacts-stitches-pane", CommitsPane)
    await page.wait_for(lambda _state: pane.result is result)
    return page, pane


def _target(entry: Any) -> ArtifactEntryTarget:
    return commit_row_target(entry)


async def test_default_mode_is_by_date_and_cycles_through_declared_modes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    result = _result()
    page, pane = await _mounted_pane(monkeypatch, result)
    try:
        mode = pane._active_grouping_mode()
        assert mode is not None
        assert mode.id == "by_date"

        assert pane.group_cycle_mode() is True
        mode = pane._active_grouping_mode()
        assert mode is not None
        assert mode.id == "by_repo"

        assert pane.group_cycle_mode() is True
        mode = pane._active_grouping_mode()
        assert mode is not None
        assert mode.id == "by_author"

        assert pane.group_cycle_mode() is True
        mode = pane._active_grouping_mode()
        assert mode is not None
        assert mode.id == "by_date"
    finally:
        await page.__aexit__(None, None, None)


async def test_collapsing_a_repo_group_hides_its_commit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    result = _result()
    assert len({entry.repo for entry in result.commits}) == 2
    page, pane = await _mounted_pane(monkeypatch, result)
    try:
        assert pane.group_cycle_mode() is True  # -> by_repo
        mode = pane._active_grouping_mode()
        assert mode is not None
        assert mode.id == "by_repo"
        before = pane.entry_targets()
        first_target = _target(result.commits[0])
        assert pane.select_entry_target(first_target)
        assert first_target in before

        assert pane.group_fold_collapse() is True
        after_collapse = pane.entry_targets()
        # Each repo has exactly one commit here, so collapsing swaps the
        # commit row for its (now collapsed) banner row 1-for-1 — the total
        # stop count is unchanged, but the collapsed repo's commit target
        # is no longer a stop and focus moved onto its banner instead.
        assert len(after_collapse) == len(before)
        assert first_target not in after_collapse
        selected = pane.selected_entry_target()
        assert selected is not None
        assert selected in after_collapse
        assert selected != first_target

        assert pane.group_fold_expand() is True
        after_expand = pane.entry_targets()
        assert after_expand == before
        assert pane.selected_entry_target() == first_target
    finally:
        await page.__aexit__(None, None, None)
