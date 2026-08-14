"""Bidirectional Beads and Plans cross-pane jumps."""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import pytest
from textual.widgets import Static

from sase.ace.testing import AcePage
from sase.ace.tui.widgets.artifacts.beads_data import BeadsSnapshot, ProjectBead
from sase.ace.tui.widgets.artifacts.beads_pane import ArtifactsBeadsPane
from sase.ace.tui.widgets.artifacts.entry_navigation import ArtifactEntryTarget
from sase.ace.tui.widgets.artifacts.plans_data import PlansSnapshot
from sase.ace.tui.widgets.artifacts.plans_pane import ArtifactsPlansPane
from sase.bead.model import Status
from tests.ace.tui._artifacts_beads_helpers import snapshot as _beads_snapshot
from tests.ace.tui._artifacts_plans_helpers import (
    _choices,
    _snapshot as _plans_snapshot,
)


def _linked_snapshots(tmp_path: Path) -> tuple[PlansSnapshot, BeadsSnapshot]:
    plans = _plans_snapshot(tmp_path)
    base = _beads_snapshot(tmp_path)
    active_link = plans.active[0].owner
    closed_link = plans.bead_plan_links[("alpha", "alpha-closed")]
    active_epic = replace(
        base.epics[0].issue,
        id=active_link.bead_id,
        status=active_link.bead_status,
        design=active_link.reference,
    )
    closed_epic = replace(
        base.epics[0].issue,
        id=closed_link.bead_id,
        title=closed_link.bead_title,
        status=Status.CLOSED,
        design=closed_link.reference,
    )
    beads = replace(
        base,
        epics=(
            ProjectBead("alpha", active_epic),
            ProjectBead("alpha", closed_epic),
        ),
        phases_by_epic={
            ("alpha", active_epic.id): (),
            ("alpha", closed_epic.id): (),
        },
        plan_links={
            ("alpha", active_epic.id): active_link.path,
            ("alpha", closed_epic.id): closed_link.path,
        },
        ready_ids=frozenset(),
        blocked_ids=frozenset(),
        source_key=("linked",),
    )
    return plans, beads


def _patch_loaders(
    monkeypatch: pytest.MonkeyPatch,
    *,
    plans: PlansSnapshot,
    beads: BeadsSnapshot,
) -> None:
    monkeypatch.setattr(
        "sase.ace.tui.actions.artifacts._collect_artifacts_project_choices",
        _choices,
    )
    monkeypatch.setattr(
        "sase.ace.tui.widgets.artifacts.plans_pane.load_plans_snapshot",
        lambda _project, **_kwargs: plans,
    )
    monkeypatch.setattr(
        "sase.ace.tui.widgets.artifacts.beads_pane.load_beads_snapshot",
        lambda _project, **_kwargs: beads,
    )


@pytest.mark.asyncio
async def test_beads_open_plan_selects_unloaded_plans_pane(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    plans, beads = _linked_snapshots(tmp_path)
    _patch_loaders(monkeypatch, plans=plans, beads=beads)

    async with AcePage(initial_tab="patches") as page:
        await page.press("3")
        beads_pane = page.query_one_widget("#artifacts-beads-pane", ArtifactsBeadsPane)
        await page.wait_for(lambda _state: beads_pane.snapshot is beads)
        assert beads_pane.select_entry_target(
            ArtifactEntryTarget(pane_id="beads", parts=("alpha", "epic", "alpha-1"))
        )

        await page.press("L")
        await page.expect_state("artifacts_subtab", "ref:plan")
        plans_pane = page.query_one_widget("#artifacts-plans-pane", ArtifactsPlansPane)
        await page.wait_for(lambda _state: plans_pane.snapshot is plans)

        assert plans_pane.selected_entry_target() == ArtifactEntryTarget(
            pane_id="ref:plan",
            parts=("alpha", "active", plans.active[0].document.path),
        )
        footer = page.query_one_widget("#keybinding-content", Static)
        assert "linked bead" in footer.content.plain


@pytest.mark.asyncio
async def test_plans_open_bead_clears_filter_and_selects_closed_bead(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    plans, beads = _linked_snapshots(tmp_path)
    _patch_loaders(monkeypatch, plans=plans, beads=beads)

    async with AcePage(initial_tab="patches") as page:
        await page.press(page.artifacts_digit("ref:plan"))
        plans_pane = page.query_one_widget("#artifacts-plans-pane", ArtifactsPlansPane)
        await page.wait_for(lambda _state: plans_pane.snapshot is plans)
        await page.press("j", "j")
        assert plans_pane.selected_row().kind == "archive"  # type: ignore[union-attr]

        await page.press("L")
        await page.expect_state("artifacts_subtab", "beads")
        beads_pane = page.query_one_widget("#artifacts-beads-pane", ArtifactsBeadsPane)
        await page.wait_for(
            lambda _state: (
                beads_pane.selected_entry_target()
                == ArtifactEntryTarget(
                    pane_id="beads", parts=("alpha", "epic", "alpha-closed")
                )
            )
        )

        assert beads_pane.filters.is_empty
        footer = page.query_one_widget("#keybinding-content", Static)
        assert "linked plan" in footer.content.plain
        assert "reopen" in footer.content.plain


@pytest.mark.asyncio
async def test_crosslink_actions_warn_when_counterpart_is_missing(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    plans, beads = _linked_snapshots(tmp_path)
    _patch_loaders(monkeypatch, plans=plans, beads=beads)

    async with AcePage(initial_tab="patches") as page:
        messages: list[tuple[str, str]] = []

        def notify(
            message: str,
            *,
            severity: str = "information",
            **_kwargs: object,
        ) -> None:
            messages.append((message, severity))

        page.app.notify = notify  # type: ignore[method-assign]

        await page.press("3")
        beads_pane = page.query_one_widget("#artifacts-beads-pane", ArtifactsBeadsPane)
        await page.wait_for(lambda _state: beads_pane.snapshot is beads)
        assert beads_pane.select_entry_target(
            ArtifactEntryTarget(pane_id="beads", parts=("alpha", "task", "alpha-open"))
        )
        page.app.action_beads_open_plan()
        assert messages[-1] == ("This bead links no plan file", "warning")

        await page.press(page.artifacts_digit("ref:plan"))
        plans_pane = page.query_one_widget("#artifacts-plans-pane", ArtifactsPlansPane)
        await page.wait_for(lambda _state: plans_pane.snapshot is plans)
        assert plans_pane.selected_row().kind == "proposal"  # type: ignore[union-attr]
        page.app.action_plans_open_bead()
        assert messages[-1] == ("No bead links this plan file", "warning")
