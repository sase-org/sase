"""Mounted navigation behavior for the Artifacts Beads pane."""

from __future__ import annotations

from pathlib import Path

import pytest

from sase.ace.testing import AcePage
from sase.ace.tui.widgets.artifacts import beads_navigation
from sase.ace.tui.widgets.artifacts.beads_pane import ArtifactsBeadsPane
from sase.ace.tui.widgets.artifacts.entry_navigation import (
    ArtifactEntryTarget,
    HydrationOutcome,
)
from sase.ace.tui.widgets.artifacts.plans_data_models import PlansProject
from sase.bead.model import BeadTier, Issue, IssueType, PhaseSize
from tests.ace.tui._artifacts_beads_helpers import snapshot


@pytest.mark.asyncio
async def test_selection_marks_jumps_and_reload_preserve_stable_target(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    value = snapshot(tmp_path, project=None)
    monkeypatch.setattr(
        "sase.ace.tui.widgets.artifacts.beads_pane.load_beads_snapshot",
        lambda _project, **_kwargs: value,
    )

    async with AcePage(initial_tab="patches") as page:
        await page.press(page.artifacts_digit("beads"))
        pane = page.query_one_widget("#artifacts-beads-pane", ArtifactsBeadsPane)
        await page.wait_for(lambda _state: pane.snapshot is value)
        targets = pane.entry_targets()
        assert targets == (
            ArtifactEntryTarget(
                pane_id="beads", parts=("alpha", "task", "alpha-ready")
            ),
            ArtifactEntryTarget(pane_id="beads", parts=("alpha", "task", "alpha-open")),
            ArtifactEntryTarget(pane_id="beads", parts=("alpha", "epic", "alpha-1")),
        )

        assert pane.select_entry_target(targets[1])
        pane.apply_entry_marks({targets[1]})
        pane.apply_entry_jump_hints({targets[1]: "A"})
        assert pane.selected_entry_target() == targets[1]

        pane._snapshot = value
        pane._refresh_options(preferred_id=pane._selected_option_id())
        assert pane.selected_entry_target() == targets[1]

        assert pane.select_entry_target(targets[2])
        pane.set_selected_epic_expanded(True)
        assert pane.entry_targets()[-1:] == (
            ArtifactEntryTarget(pane_id="beads", parts=("alpha", "phase", "alpha-1.2")),
        )


@pytest.mark.asyncio
async def test_hydrate_ref_resolves_exact_bead_and_preserves_phase_grouping(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A phase never loaded is hydrated with its parent epic for free."""
    value = snapshot(tmp_path, project=None)
    monkeypatch.setattr(
        "sase.ace.tui.widgets.artifacts.beads_pane.load_beads_snapshot",
        lambda _project, **_kwargs: value,
    )
    beads_dir = Path(value.beads_dirs["alpha"])
    monkeypatch.setattr(
        beads_navigation,
        "_resolve_projects",
        lambda _scope: (PlansProject("alpha", "Alpha", str(tmp_path / "workspace")),),
    )
    monkeypatch.setattr(
        beads_navigation, "_project_beads_dir", lambda _project: beads_dir
    )

    hydrated_epic = Issue(
        id="alpha-2",
        title="Second epic",
        issue_type=IssueType.PLAN,
        tier=BeadTier.EPIC,
        created_at="2026-07-10T09:00:00Z",
        updated_at="2026-07-10T09:00:00Z",
    )
    hydrated_phase = Issue(
        id="alpha-2.1",
        title="Hydrated phase",
        issue_type=IssueType.PHASE,
        parent_id=hydrated_epic.id,
        size=PhaseSize.SMALL,
        created_at="2026-07-10T09:00:00Z",
        updated_at="2026-07-10T09:00:00Z",
    )

    def fake_resolve_id(dir_path: Path, issue_id: str) -> str:
        assert str(dir_path) == str(beads_dir)
        if issue_id in {"alpha-2.1", "alpha-2"}:
            return issue_id
        raise KeyError(issue_id)

    def fake_show(dir_path: Path, full_id: str) -> Issue:
        assert str(dir_path) == str(beads_dir)
        if full_id == "alpha-2.1":
            return hydrated_phase
        if full_id == "alpha-2":
            return hydrated_epic
        raise KeyError(full_id)

    monkeypatch.setattr("sase.core.bead_read_facade.resolve_id", fake_resolve_id)
    monkeypatch.setattr("sase.core.bead_read_facade.show", fake_show)

    async with AcePage(initial_tab="patches") as page:
        await page.press(page.artifacts_digit("beads"))
        pane = page.query_one_widget("#artifacts-beads-pane", ArtifactsBeadsPane)
        await page.wait_for(lambda _state: pane.snapshot is value)

        outcome = pane.hydrate_ref("bead", "alpha-2.1")
        assert outcome.outcome is HydrationOutcome.FETCHED
        project, issue, parent_epic = outcome.payload
        assert project == "alpha"
        assert issue.id == "alpha-2.1"
        assert parent_epic is not None
        assert parent_epic.id == "alpha-2"

        before_epic_count = len(pane.snapshot.epics)
        target = pane.install_hydrated_row(outcome.payload)

        assert target == ArtifactEntryTarget("beads", ("alpha", "phase", "alpha-2.1"))
        assert pane.snapshot is not None
        assert len(pane.snapshot.epics) == before_epic_count + 1
        assert any(bead.issue.id == "alpha-2" for bead in pane.snapshot.epics)
        phases = pane.snapshot.phases_by_epic[("alpha", "alpha-2")]
        assert [bead.issue.id for bead in phases] == ["alpha-2.1"]

        # Idempotent: re-installing the identical row does not duplicate it.
        replay = pane.install_hydrated_row(outcome.payload)
        assert replay == target
        assert len(pane.snapshot.epics) == before_epic_count + 1
        assert len(pane.snapshot.phases_by_epic[("alpha", "alpha-2")]) == 1


@pytest.mark.asyncio
async def test_hydrate_ref_reports_absent_for_unknown_bead_id(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    value = snapshot(tmp_path, project=None)
    monkeypatch.setattr(
        "sase.ace.tui.widgets.artifacts.beads_pane.load_beads_snapshot",
        lambda _project, **_kwargs: value,
    )
    beads_dir = Path(value.beads_dirs["alpha"])
    monkeypatch.setattr(
        beads_navigation,
        "_resolve_projects",
        lambda _scope: (PlansProject("alpha", "Alpha", str(tmp_path / "workspace")),),
    )
    monkeypatch.setattr(
        beads_navigation, "_project_beads_dir", lambda _project: beads_dir
    )

    def fake_resolve_id(dir_path: Path, issue_id: str) -> str:
        raise KeyError(issue_id)

    monkeypatch.setattr("sase.core.bead_read_facade.resolve_id", fake_resolve_id)

    async with AcePage(initial_tab="patches") as page:
        await page.press(page.artifacts_digit("beads"))
        pane = page.query_one_widget("#artifacts-beads-pane", ArtifactsBeadsPane)
        await page.wait_for(lambda _state: pane.snapshot is value)

        outcome = pane.hydrate_ref("bead", "alpha-999")
        assert outcome.outcome is HydrationOutcome.ABSENT


@pytest.mark.asyncio
async def test_detail_scroll_reserves_its_gutter_so_the_width_never_oscillates(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The detail pane's content width must not depend on the scrollbar.

    The Created property value fills the content width exactly, so an auto
    gutter gives one bead two stable layouts: without a scrollbar the value
    fits on one line, and with one it wraps, which adds the very line that
    keeps the scrollbar. The reserved gutter collapses that to one layout.
    """
    value = snapshot(tmp_path, project=None)
    monkeypatch.setattr(
        "sase.ace.tui.widgets.artifacts.beads_pane.load_beads_snapshot",
        lambda _project, **_kwargs: value,
    )

    async with AcePage(initial_tab="patches") as page:
        await page.press(page.artifacts_digit("beads"))
        pane = page.query_one_widget("#artifacts-beads-pane", ArtifactsBeadsPane)
        await page.wait_for(lambda _state: pane.snapshot is value)
        scroll = pane.query_one("#beads-detail-scroll")

        assert scroll.styles.scrollbar_gutter == "stable"

        width_without_scrollbar = scroll.content_region.width
        scroll.show_vertical_scrollbar = True
        assert scroll.content_region.width == width_without_scrollbar
