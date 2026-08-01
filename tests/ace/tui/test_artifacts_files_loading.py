"""Off-thread loading and navigation coverage for Artifacts Files."""

from __future__ import annotations

from threading import Event

import pytest
from textual.widgets import OptionList, Static

from sase.ace.testing import AcePage
from sase.ace.tui.widgets.artifacts import files_data, files_pane
from sase.ace.tui.widgets.artifacts.files_pane import ArtifactsFilesPane
from tests.ace.tui._artifacts_files_helpers import artifact_file, snapshot
from tests.ace.tui._artifacts_plans_helpers import _choices


def test_data_loader_uses_only_project_scope_and_limit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    row = artifact_file("query")
    calls: list[dict[str, object]] = []

    def query(**kwargs: object):
        calls.append(dict(kwargs))
        return [row]

    monkeypatch.setattr(files_data, "query_artifact_files", query)
    result = files_data.load_files_snapshot("alpha", 500)

    assert calls == [{"project": "alpha", "limit": 500}]
    assert result.rows == (row,)
    assert result.complete is True
    assert result.load_error is None


def test_data_loader_degrades_binding_errors(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fail(**_kwargs: object):
        raise RuntimeError("stale artifact-file binding")

    monkeypatch.setattr(files_data, "query_artifact_files", fail)
    result = files_data.load_files_snapshot(None, 500)

    assert result.rows == ()
    assert result.complete is True
    assert result.load_error == "stale artifact-file binding"


async def test_first_page_paints_before_full_extension(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    first_rows = (
        artifact_file("newest"),
        artifact_file("older", created_at="2026-07-23T13:10:00-04:00"),
    )
    full_rows = (
        *first_rows,
        artifact_file("oldest", created_at="2026-07-22T09:00:00-04:00"),
    )
    full_started = Event()
    release_full = Event()
    requested_limits: list[int | None] = []

    def load(project: str | None, limit: int | None):
        requested_limits.append(limit)
        if limit is None:
            full_started.set()
            assert release_full.wait(timeout=5)
            return snapshot(full_rows, project=project)
        return snapshot(first_rows, project=project, complete=False)

    monkeypatch.setattr(
        "sase.ace.tui.actions.artifacts._collect_artifacts_project_choices",
        _choices,
    )
    monkeypatch.setattr(files_pane, "load_files_snapshot", load)

    try:
        async with AcePage(initial_tab="changespecs") as page:
            await page.press("5", "(")
            pane = page.query_one_widget(
                "#artifacts-files-pane",
                ArtifactsFilesPane,
            )
            await page.wait_for(
                lambda _state: (
                    pane.snapshot is not None and len(pane.snapshot.rows) == 2
                )
            )

            assert pane.selected_entry is first_rows[0]
            assert pane.entry_targets() == (
                ("file", first_rows[0].id),
                ("file", first_rows[1].id),
            )
            assert full_started.wait(timeout=2)
            assert requested_limits[:2] == [500, None]

            release_full.set()
            await page.wait_for(
                lambda _state: (
                    pane.snapshot is not None
                    and pane.snapshot.complete
                    and len(pane.snapshot.rows) == 3
                )
            )
            assert pane.selected_entry is first_rows[0]
    finally:
        release_full.set()


async def test_error_snapshot_renders_status_without_crashing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "sase.ace.tui.actions.artifacts._collect_artifacts_project_choices",
        _choices,
    )
    monkeypatch.setattr(
        files_pane,
        "load_files_snapshot",
        lambda project, _limit: snapshot(
            (),
            project=project,
            load_error="stale artifact-file binding",
        ),
    )

    async with AcePage(initial_tab="changespecs") as page:
        await page.press("5", "(")
        pane = page.query_one_widget("#artifacts-files-pane", ArtifactsFilesPane)
        await page.wait_for(
            lambda _state: (
                pane.snapshot is not None and pane.snapshot.load_error is not None
            )
        )
        status = pane.query_one("#files-status", Static)
        assert "stale artifact-file binding" in status.content.plain


async def test_cursor_survives_refresh_and_jk_has_no_highlight_echoes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    rows = (
        artifact_file("first"),
        artifact_file("second", created_at="2026-07-23T13:10:00-04:00"),
        artifact_file("third", created_at="2026-07-22T13:10:00-04:00"),
    )
    calls = 0

    def load(project: str | None, _limit: int | None):
        nonlocal calls
        calls += 1
        return snapshot(rows, project=project)

    monkeypatch.setattr(
        "sase.ace.tui.actions.artifacts._collect_artifacts_project_choices",
        _choices,
    )
    monkeypatch.setattr(files_pane, "load_files_snapshot", load)

    async with AcePage(initial_tab="changespecs") as page:
        await page.press("5", "(")
        pane = page.query_one_widget("#artifacts-files-pane", ArtifactsFilesPane)
        await page.wait_for(lambda _state: pane.selected_entry is rows[0])
        option_list = pane.query_one("#files-list", OptionList)
        assert option_list.highlighted == 1

        await page.press("j")
        assert pane.selected_entry is rows[1]
        await page.press("k")
        assert pane.selected_entry is rows[0]
        assert pane.select_entry_target(("file", rows[1].id))
        assert pane.selected_entry is rows[1]

        before_refresh = calls
        await page.press("R")
        await page.wait_for(lambda _state: calls > before_refresh)
        await page.wait_for(lambda _state: pane.selected_entry is rows[1])
        assert pane.selected_entry_target() == ("file", rows[1].id)

        await page.press("g")
        assert pane.selected_entry is rows[0]
        await page.press("G")
        assert pane.selected_entry is rows[-1]
        selected = pane.selected_entry_target()
        assert selected is not None
        pane.apply_entry_jump_hints({selected: "A"})
        assert pane.selected_entry_target() == selected
        pane.clear_entry_jump_hints()
        pane.apply_entry_marks({selected})
        assert pane.selected_entry_target() == selected
