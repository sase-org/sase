"""Plan-then-commit Beads reveals: session context queries end to end."""

from __future__ import annotations

from pathlib import Path

import pytest
from textual.widgets import Static

from sase.ace.link_reveal_context import explain_hidden
from sase.ace.testing import AcePage
from sase.ace.tui.actions.link_follow import _link_follow_outcomes
from sase.ace.tui.widgets.artifacts import beads_pane
from sase.ace.tui.widgets.artifacts.bead_filter_bar import BeadFilterBar
from sase.ace.tui.widgets.artifacts.beads_pane import ArtifactsBeadsPane
from sase.ace.tui.widgets.artifacts.entry_navigation import HydrationOutcome
from sase.ace.tui.widgets.artifacts.entry_navigation import HydrationResult
from sase.core.artifact_entry_target import ArtifactEntryTarget
from tests.ace.tui._artifacts_beads_helpers import snapshot as beads_snapshot


async def _open_beads(
    page: AcePage, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> ArtifactsBeadsPane:
    monkeypatch.setattr(
        beads_pane,
        "load_beads_snapshot",
        lambda project, **_kwargs: beads_snapshot(tmp_path, project=project),
    )
    await page.press(page.artifacts_digit("beads"))
    pane = page.query_one_widget("#artifacts-beads-pane", ArtifactsBeadsPane)
    pane.set_project_scope("alpha")
    await page.wait_for(
        lambda _state: pane.snapshot is not None and pane.snapshot.project == "alpha"
    )
    return pane


async def _set_query(page: AcePage, pane: ArtifactsBeadsPane, query: str) -> None:
    bar = pane.query_one(BeadFilterBar)
    display = bar.query_one("#bead-filter-display", Static)
    await page.press("/")
    bar.set_query(query)
    bar.post_message(BeadFilterBar.Submitted(query))
    await page.wait_for(lambda _state: not bar._editing)  # type: ignore[attr-defined]
    await page.wait_for(lambda _state: query in display.render().plain)


async def test_phase_context_rewrite_selects_and_restores(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async with AcePage(initial_tab="patches") as page:
        pane = await _open_beads(page, tmp_path, monkeypatch)
        await _set_query(page, pane, "-status:closed limit:100")
        before = ArtifactEntryTarget("beads", ("alpha", "task", "alpha-ready"))
        assert pane.select_entry_target(before)

        app = page.app
        origin = app._current_link_trail_origin()
        chip = ArtifactEntryTarget("beads", ("alpha", "task", "alpha-1.1"))
        app._follow_artifacts_target("bead:alpha-1.1", chip, origin)
        await page.wait_for(lambda _state: app._link_follow_transaction is None)

        target = ArtifactEntryTarget("beads", ("alpha", "phase", "alpha-1.1"))
        assert pane.selected_entry_target() == target
        assert pane.host_limit_query() == "id:alpha-1.* limit:100"
        assert _link_follow_outcomes["context"] == 1

        reveal = app._link_reveals["beads"]
        assert reveal.origin.canonical == "-status:closed limit:100"
        assert reveal.label == "epic alpha-1"
        probe = pane.host_query_probe(target)
        reason = explain_hidden(probe, reveal.origin.canonical, pane._query_profile)
        assert reason.kind == "filtered"
        assert "-status:closed" in reason.terms

        app.action_prev_query()
        await page.wait_for(
            lambda _state: pane.host_limit_query() == "-status:closed limit:100"
        )
        assert pane.selected_entry_target() == before


async def test_epic_context_selects_and_expands(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async with AcePage(initial_tab="patches") as page:
        pane = await _open_beads(page, tmp_path, monkeypatch)
        await _set_query(page, pane, "id:alpha-open")

        app = page.app
        origin = app._current_link_trail_origin()
        chip = ArtifactEntryTarget("beads", ("alpha", "task", "alpha-1"))
        app._follow_artifacts_target("bead:alpha-1", chip, origin)
        await page.wait_for(lambda _state: app._link_follow_transaction is None)

        target = ArtifactEntryTarget("beads", ("alpha", "epic", "alpha-1"))
        assert pane.selected_entry_target() == target
        assert pane.host_limit_query() == "id:alpha-1 id:alpha-1.*"
        phase = ArtifactEntryTarget("beads", ("alpha", "phase", "alpha-1.1"))
        assert phase in pane.entry_targets()


async def test_task_context_preserves_small_limit(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async with AcePage(initial_tab="patches") as page:
        pane = await _open_beads(page, tmp_path, monkeypatch)
        await _set_query(page, pane, "limit:1")

        app = page.app
        origin = app._current_link_trail_origin()
        chip = ArtifactEntryTarget("beads", ("alpha", "task", "alpha-open"))
        app._follow_artifacts_target("bead:alpha-open", chip, origin)
        await page.wait_for(lambda _state: app._link_follow_transaction is None)

        target = ArtifactEntryTarget("beads", ("alpha", "task", "alpha-open"))
        assert pane.selected_entry_target() == target
        assert pane.host_limit_query() == "id:alpha-open limit:1"


async def test_second_jump_while_lens_live_restores_original(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async with AcePage(initial_tab="patches") as page:
        pane = await _open_beads(page, tmp_path, monkeypatch)
        await _set_query(page, pane, "-status:closed limit:100")
        before = ArtifactEntryTarget("beads", ("alpha", "task", "alpha-ready"))
        assert pane.select_entry_target(before)

        app = page.app
        origin = app._current_link_trail_origin()
        chip = ArtifactEntryTarget("beads", ("alpha", "task", "alpha-1.1"))
        app._follow_artifacts_target("bead:alpha-1.1", chip, origin)
        await page.wait_for(lambda _state: app._link_follow_transaction is None)
        first_query = pane.host_limit_query()
        assert first_query == "id:alpha-1.* limit:100"

        second = ArtifactEntryTarget("beads", ("alpha", "phase", "alpha-1.2"))
        origin2 = app._current_link_trail_origin()
        app._follow_artifacts_target("bead:alpha-1.2", second, origin2)
        await page.wait_for(lambda _state: app._link_follow_transaction is None)
        assert pane.selected_entry_target() == second
        assert pane.host_limit_query() == first_query

        app.action_prev_query()
        await page.wait_for(
            lambda _state: pane.host_limit_query() == "-status:closed limit:100"
        )


async def test_missing_bead_hydrates_then_reveals(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from sase.bead.model import Issue, IssueType, Status

    async with AcePage(initial_tab="patches") as page:
        pane = await _open_beads(page, tmp_path, monkeypatch)
        await _set_query(page, pane, "-status:closed limit:100")

        issue = Issue(
            id="alpha-missing",
            title="Hydrated follow-up",
            status=Status.CLOSED,
            issue_type=IssueType.TASK,
        )

        def hydrate(kind: str, payload: str) -> HydrationResult:
            assert (kind, payload) == ("bead", "alpha-missing")
            return HydrationResult(
                HydrationOutcome.FETCHED, payload=("alpha", issue, None)
            )

        monkeypatch.setattr(pane, "hydrate_ref", hydrate)

        app = page.app
        origin = app._current_link_trail_origin()
        chip = ArtifactEntryTarget("beads", ("alpha", "task", "alpha-missing"))
        app._follow_artifacts_target("bead:alpha-missing", chip, origin)
        await page.wait_for(lambda _state: app._link_follow_transaction is None)

        target = ArtifactEntryTarget("beads", ("alpha", "task", "alpha-missing"))
        assert pane.selected_entry_target() == target
        assert pane.host_limit_query() == "id:alpha-missing limit:100"
