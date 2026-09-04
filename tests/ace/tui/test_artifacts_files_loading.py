"""Off-thread loading and navigation coverage for Artifacts Files."""

from __future__ import annotations

from threading import Event

import pytest
from textual.widgets import OptionList, Static

from sase.ace.testing import AcePage
from sase.ace.tui.widgets.artifacts import files_data, files_pane
from sase.ace.tui.widgets.artifacts.entry_navigation import (
    ArtifactEntryTarget,
    HydrationOutcome,
    LinkRequestState,
)
from sase.ace.tui.widgets.artifacts.files_pane import ArtifactsFilesPane
from tests.ace.tui._artifacts_files_helpers import (
    artifact_file,
    logical_file,
    snapshot,
)
from tests.ace.tui._artifacts_plans_helpers import _choices
from tests._load_tolerant import LOAD_TOLERANT_TIMEOUT


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
    assert result.rows == (logical_file(row),)
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
            assert release_full.wait(timeout=LOAD_TOLERANT_TIMEOUT)
            return snapshot(full_rows, project=project)
        return snapshot(first_rows, project=project, complete=False)

    monkeypatch.setattr(
        "sase.ace.tui.actions.artifacts._collect_artifacts_project_choices",
        _choices,
    )
    monkeypatch.setattr(files_pane, "load_files_snapshot", load)

    try:
        async with AcePage(initial_tab="patches") as page:
            await page.press(page.artifacts_digit("files"), "(")
            pane = page.query_one_widget(
                "#artifacts-files-pane",
                ArtifactsFilesPane,
            )
            await page.wait_for(
                lambda _state: (
                    pane.snapshot is not None and len(pane.snapshot.rows) == 2
                ),
                timeout=LOAD_TOLERANT_TIMEOUT,
            )

            assert pane.selected_entry is not None
            assert pane.selected_entry.id == first_rows[0].id
            # Both rows default to "capture" origin and share one "by_source"
            # banner, but the banner starts expanded (not collapsed), so it's
            # a visible header, not a navigation/jump stop.
            assert pane.entry_targets() == (
                ArtifactEntryTarget(
                    pane_id="files", parts=(logical_file(first_rows[0]).logical_id,)
                ),
                ArtifactEntryTarget(
                    pane_id="files", parts=(logical_file(first_rows[1]).logical_id,)
                ),
            )
            assert full_started.wait(timeout=LOAD_TOLERANT_TIMEOUT)
            assert requested_limits[:2] == [500, None]

            release_full.set()
            await page.wait_for(
                lambda _state: (
                    pane.snapshot is not None
                    and pane.snapshot.complete
                    and len(pane.snapshot.rows) == 3
                ),
                timeout=LOAD_TOLERANT_TIMEOUT,
            )
            assert pane.selected_entry is not None
            assert pane.selected_entry.id == first_rows[0].id
    finally:
        release_full.set()


async def test_request_entry_target_defers_until_a_matching_snapshot_loads(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A deep link to a not-yet-loaded row is remembered and resolved later."""
    first_rows = (artifact_file("newest"),)
    linked = artifact_file("linked", created_at="2026-07-22T09:00:00-04:00")
    full_rows = (*first_rows, linked)
    release_full = Event()

    def load(project: str | None, limit: int | None):
        if limit is None:
            assert release_full.wait(timeout=LOAD_TOLERANT_TIMEOUT)
            return snapshot(full_rows, project=project)
        return snapshot(first_rows, project=project, complete=False)

    monkeypatch.setattr(
        "sase.ace.tui.actions.artifacts._collect_artifacts_project_choices",
        _choices,
    )
    monkeypatch.setattr(files_pane, "load_files_snapshot", load)

    try:
        async with AcePage(initial_tab="patches") as page:
            await page.press(page.artifacts_digit("files"), "(")
            pane = page.query_one_widget(
                "#artifacts-files-pane",
                ArtifactsFilesPane,
            )
            await page.wait_for(
                lambda _state: (
                    pane.snapshot is not None and len(pane.snapshot.rows) == 1
                ),
                timeout=LOAD_TOLERANT_TIMEOUT,
            )

            target = ArtifactEntryTarget(
                pane_id="files", parts=(logical_file(linked).logical_id,)
            )
            assert pane.request_entry_target(target) is LinkRequestState.PENDING
            assert pane._pending_entry_target == target

            release_full.set()
            await page.wait_for(
                lambda _state: (
                    pane.snapshot is not None and len(pane.snapshot.rows) == 2
                ),
                timeout=LOAD_TOLERANT_TIMEOUT,
            )
            await page.wait_for(
                lambda _state: pane._pending_entry_target is None,
                timeout=LOAD_TOLERANT_TIMEOUT,
            )

            assert pane.selected_entry_target() == target
    finally:
        release_full.set()


async def test_hydrate_ref_resolves_exact_file_by_logical_id(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A file the pane's capped snapshot never fetched is hydrated directly."""
    existing_row = artifact_file("known")
    hydrated_row = artifact_file("never-fetched", artifact_id="hydrated:abc")

    monkeypatch.setattr(
        "sase.ace.tui.actions.artifacts._collect_artifacts_project_choices",
        _choices,
    )
    monkeypatch.setattr(
        files_pane,
        "load_files_snapshot",
        lambda project, limit: snapshot((existing_row,), project=project),
    )

    async with AcePage(initial_tab="patches") as page:
        await page.press(page.artifacts_digit("files"), "(")
        pane = page.query_one_widget("#artifacts-files-pane", ArtifactsFilesPane)
        await page.wait_for(
            lambda _state: pane.snapshot is not None and len(pane.snapshot.rows) == 1,
        )

        calls: list[dict[str, object]] = []

        def fake_query_artifact_files(**kwargs: object) -> list:
            calls.append(dict(kwargs))
            return [hydrated_row]

        def fake_query_ref_file_versions() -> list:
            return []

        monkeypatch.setattr(
            files_data, "query_artifact_files", fake_query_artifact_files
        )
        monkeypatch.setattr(
            files_data, "query_ref_file_versions", fake_query_ref_file_versions
        )

        target_logical_id = logical_file(hydrated_row).logical_id
        outcome = pane.hydrate_ref("file", target_logical_id)

        assert outcome.outcome is HydrationOutcome.FETCHED
        payload = outcome.payload
        assert isinstance(payload, files_data.LogicalFile)
        assert payload.logical_id == target_logical_id
        # Scoped to this pane's project, never a global scan.
        assert calls == [{"project": pane.project_scope, "limit": None}]

        before = len(pane.snapshot.rows)
        new_target = pane.install_hydrated_row(payload)

        assert new_target == ArtifactEntryTarget(
            pane_id="files", parts=(target_logical_id,)
        )
        assert pane.snapshot is not None
        assert len(pane.snapshot.rows) == before + 1
        assert any(row.logical_id == target_logical_id for row in pane.snapshot.rows)

        # A repeated hydration of the same id is a no-op merge.
        replay_target = pane.install_hydrated_row(payload)
        assert replay_target == new_target
        assert len(pane.snapshot.rows) == before + 1


async def test_hydrate_ref_reports_absent_for_unknown_logical_id(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "sase.ace.tui.actions.artifacts._collect_artifacts_project_choices",
        _choices,
    )
    monkeypatch.setattr(
        files_pane,
        "load_files_snapshot",
        lambda project, limit: snapshot((), project=project),
    )

    async with AcePage(initial_tab="patches") as page:
        await page.press(page.artifacts_digit("files"), "(")
        pane = page.query_one_widget("#artifacts-files-pane", ArtifactsFilesPane)
        await page.wait_for(lambda _state: pane.snapshot is not None)

        monkeypatch.setattr(files_data, "query_artifact_files", lambda **_kw: [])
        monkeypatch.setattr(files_data, "query_ref_file_versions", lambda: [])

        outcome = pane.hydrate_ref("file", "no/such/file.txt")
        assert outcome.outcome is HydrationOutcome.ABSENT


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

    async with AcePage(initial_tab="patches") as page:
        await page.press(page.artifacts_digit("files"), "(")
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

    async with AcePage(initial_tab="patches") as page:
        await page.press(page.artifacts_digit("files"), "(")
        pane = page.query_one_widget("#artifacts-files-pane", ArtifactsFilesPane)
        await page.wait_for(
            lambda _state: (
                pane.selected_entry is not None and pane.selected_entry.id == rows[0].id
            )
        )
        option_list = pane.query_one("#files-list", OptionList)
        assert option_list.highlighted == 1

        await page.press("j")
        assert pane.selected_entry is not None
        assert pane.selected_entry.id == rows[1].id
        await page.press("k")
        assert pane.selected_entry is not None
        assert pane.selected_entry.id == rows[0].id
        assert pane.select_entry_target(
            ArtifactEntryTarget(
                pane_id="files", parts=(logical_file(rows[1]).logical_id,)
            )
        )
        assert pane.selected_entry is not None
        assert pane.selected_entry.id == rows[1].id

        before_refresh = calls
        await page.press("R")
        await page.wait_for(lambda _state: calls > before_refresh)
        await page.wait_for(
            lambda _state: (
                pane.selected_entry is not None and pane.selected_entry.id == rows[1].id
            )
        )
        assert pane.selected_entry_target() == ArtifactEntryTarget(
            pane_id="files", parts=(logical_file(rows[1]).logical_id,)
        )

        await page.press("g")
        assert pane.selected_entry is not None
        assert pane.selected_entry.id == rows[0].id
        await page.press("G")
        assert pane.selected_entry is not None
        assert pane.selected_entry.id == rows[-1].id
        selected = pane.selected_entry_target()
        assert selected is not None
        pane.apply_entry_jump_hints({selected: "A"})
        assert pane.selected_entry_target() == selected
        pane.clear_entry_jump_hints()
        pane.apply_entry_marks({selected})
        assert pane.selected_entry_target() == selected
