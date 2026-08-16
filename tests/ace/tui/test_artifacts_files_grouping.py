"""Shared-registry grouping/fold behavior for the Artifacts Files pane."""

from __future__ import annotations

import pytest

from sase.ace.testing import AcePage
from sase.ace.tui.widgets.artifacts import files_pane
from sase.ace.tui.widgets.artifacts.entry_navigation import ArtifactEntryTarget
from sase.ace.tui.widgets.artifacts.files_pane import ArtifactsFilesPane
from sase.core.artifact_file_types import ArtifactFile
from tests.ace.tui._artifacts_files_helpers import artifact_file, logical_file, snapshot
from tests.ace.tui._artifacts_plans_helpers import _choices


def _target(row: ArtifactFile) -> ArtifactEntryTarget:
    return ArtifactEntryTarget(pane_id="files", parts=(logical_file(row).logical_id,))


def _patch_loader(
    monkeypatch: pytest.MonkeyPatch,
    rows: tuple[ArtifactFile, ...],
) -> None:
    monkeypatch.setattr(
        "sase.ace.tui.actions.artifacts._collect_artifacts_project_choices",
        _choices,
    )
    monkeypatch.setattr(
        files_pane,
        "load_files_snapshot",
        lambda project, _limit: snapshot(rows, project=project),
    )


async def test_default_mode_is_by_source_and_cycles_through_declared_modes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    rows = (artifact_file("only", kind="markdown"),)
    _patch_loader(monkeypatch, rows)
    async with AcePage(initial_tab="patches") as page:
        await page.press(page.artifacts_digit("files"), "(")
        pane = page.query_one_widget("#artifacts-files-pane", ArtifactsFilesPane)
        await page.wait_for(lambda _state: pane.snapshot is not None)

        mode = pane._active_grouping_mode()
        assert mode is not None
        assert mode.id == "by_source"

        assert pane.group_cycle_mode() is True
        mode = pane._active_grouping_mode()
        assert mode is not None
        assert mode.id == "by_kind"

        assert pane.group_cycle_mode() is True
        mode = pane._active_grouping_mode()
        assert mode is not None
        assert mode.id == "by_project"

        assert pane.group_cycle_mode() is True
        mode = pane._active_grouping_mode()
        assert mode is not None
        assert mode.id == "by_source"


async def test_collapsing_a_group_hides_members_and_becomes_the_only_stop(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    rows = (
        artifact_file("first", kind="markdown"),
        artifact_file(
            "second", kind="markdown", created_at="2026-07-23T13:10:00-04:00"
        ),
        artifact_file("third", kind="pdf", created_at="2026-07-22T13:10:00-04:00"),
    )
    _patch_loader(monkeypatch, rows)
    async with AcePage(initial_tab="patches") as page:
        await page.press(page.artifacts_digit("files"), "(")
        pane = page.query_one_widget("#artifacts-files-pane", ArtifactsFilesPane)
        await page.wait_for(lambda _state: pane.snapshot is not None)

        assert pane.group_cycle_mode() is True  # -> by_kind
        mode = pane._active_grouping_mode()
        assert mode is not None
        assert mode.id == "by_kind"
        before = len(pane.entry_targets())
        assert pane.select_entry_target(_target(rows[0]))

        assert pane.group_fold_collapse() is True
        targets_after_collapse = pane.entry_targets()
        # 3 real rows collapse into markdown+pdf banners; collapsing the
        # markdown group leaves: [markdown banner (collapsed), pdf banner
        # (still expanded, not a stop), pdf row].
        assert len(targets_after_collapse) < before
        selected = pane.selected_entry_target()
        assert selected is not None
        assert selected in targets_after_collapse
        assert pane.selected_entry is None  # focus is on the banner, not a row

        assert pane.group_fold_expand() is True
        targets_after_expand = pane.entry_targets()
        assert len(targets_after_expand) == before
        assert pane.selected_entry is not None
        assert pane.selected_entry.id == rows[0].id


async def test_fold_state_is_kept_per_mode_across_cycling(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    rows = (
        artifact_file("first", kind="markdown"),
        artifact_file("second", kind="pdf", created_at="2026-07-23T13:10:00-04:00"),
    )
    _patch_loader(monkeypatch, rows)
    async with AcePage(initial_tab="patches") as page:
        await page.press(page.artifacts_digit("files"), "(")
        pane = page.query_one_widget("#artifacts-files-pane", ArtifactsFilesPane)
        await page.wait_for(lambda _state: pane.snapshot is not None)

        assert pane.group_cycle_mode() is True  # -> by_kind
        assert pane.select_entry_target(_target(rows[0]))
        assert pane.group_fold_collapse() is True
        collapsed_count = len(pane.entry_targets())

        assert pane.group_cycle_mode() is True  # -> by_project
        assert pane.group_cycle_mode(reverse=True) is True  # back to by_kind
        mode = pane._active_grouping_mode()
        assert mode is not None
        assert mode.id == "by_kind"
        assert len(pane.entry_targets()) == collapsed_count
