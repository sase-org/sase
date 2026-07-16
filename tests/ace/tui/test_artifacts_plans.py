"""Plans-pane data, navigation, and tracked-action coverage."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import Mock

import pytest
from textual.widgets import OptionList

from sase.ace.testing import AcePage
from sase.ace.tui.actions.artifacts import _ArtifactsProjectChoices
from sase.ace.tui.modals.inventory_project_picker import InventoryProjectChoice
from sase.ace.tui.widgets.artifacts.plans_data import (
    PlanProposal,
    PlansSnapshot,
    load_plans_snapshot,
)
from sase.ace.tui.widgets.artifacts.plans_pane import ArtifactsPlansPane
from sase.bead.model import BeadTier, Dependency, Issue, IssueType, Status
from sase.bead.project import BeadProject
from sase.notifications.models import Notification
from sase.plan_search.model import Plan, PlanSearchMatch


def _choices() -> _ArtifactsProjectChoices:
    return _ArtifactsProjectChoices(
        choices=(
            InventoryProjectChoice(
                project_key="alpha",
                display_name="Alpha",
                state="enabled",
            ),
        ),
        enabled_projects=("alpha",),
        display_names={"alpha": "Alpha"},
    )


def _snapshot(tmp_path: Path) -> PlansSnapshot:
    notification = Notification(
        id="proposal-1",
        timestamp="2026-07-15T12:00:00+00:00",
        sender="planner",
        files=[str(tmp_path / "proposal.md")],
        action="PlanApproval",
        action_data={"response_dir": str(tmp_path / "approval")},
    )
    proposal = PlanProposal(
        notification=notification,
        title="Ship the plan browser",
        tier="epic",
        age="2m ago",
        timestamp=notification.timestamp,
        plan_path=notification.files[0],
        content="# Ship the plan browser\n\nProposal body.",
        agent="alpha.plan",
        provider_model="codex/gpt-5",
    )
    epic = Issue(
        id="alpha-1",
        title="Artifacts plans",
        status=Status.OPEN,
        issue_type=IssueType.PLAN,
        tier=BeadTier.EPIC,
        description="Build the Plans pane.",
        changespec_name="alpha-cl",
        changespec_bug_id="42",
    )
    first = Issue(
        id="alpha-1.1",
        title="Load plans",
        issue_type=IssueType.PHASE,
        parent_id=epic.id,
        model="codex/gpt-5",
    )
    second = Issue(
        id="alpha-1.2",
        title="Render dependency state",
        issue_type=IssueType.PHASE,
        parent_id=epic.id,
        dependencies=[
            Dependency(
                issue_id="alpha-1.2",
                depends_on_id="alpha-1.1",
                created_at="2026-07-15T12:00:00Z",
            )
        ],
    )
    archive = PlanSearchMatch(
        plan=Plan(
            source="repo",
            kind="epic",
            path=str(tmp_path / "202607" / "archive.md"),
            relpath="202607/archive.md",
            name="archive",
            title="Archived rollout",
            status="done",
            created_at="2026-07-14 10:00:00",
            prompt_link="",
            summary="The archived plan summary.",
            body="# Rollout\n\nDone.",
            frontmatter={"tier": "epic", "status": "done"},
        ),
        matched_fields=[],
        score=1.0,
    )
    return PlansSnapshot(
        project="alpha",
        beads_dir=str(tmp_path / "beads"),
        plans_root=str(tmp_path),
        workspace_dir=str(tmp_path / "workspace"),
        proposals=(proposal,),
        epics=(epic,),
        phases_by_epic={epic.id: (first, second)},
        ready_ids=frozenset({epic.id, first.id}),
        blocked_ids=frozenset({second.id}),
        archive=(archive,),
        source_key=("fixture",),
    )


def test_snapshot_reads_fixture_bead_dag_and_flat_plan_archive(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    plans_root = tmp_path / "alpha--plans"
    with BeadProject.init(plans_root, beads_dirname="beads") as project:
        epic = project.create(
            "Fixture epic",
            IssueType.PLAN,
            tier=BeadTier.EPIC,
            description="Fixture description",
        )
        first = project.create("First phase", IssueType.PHASE, parent_id=epic.id)
        second = project.create("Second phase", IssueType.PHASE, parent_id=epic.id)
        project.add_dependency(second.id, first.id)

    month = plans_root / "202607"
    month.mkdir()
    (month / "fixture.md").write_text(
        "---\ntier: epic\nstatus: wip\ncreate_time: 2026-07-15 12:00:00\n---\n"
        "# Fixture archive\n\nRendered body.\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(
        "sase.ace.tui.widgets.artifacts.plans_data._project_beads_dir",
        lambda _project: plans_root / "beads",
    )
    monkeypatch.setattr(
        "sase.ace.tui.widgets.artifacts.plans_data._project_workspace_dir",
        lambda _project: str(tmp_path / "workspace"),
    )
    monkeypatch.setattr(
        "sase.ace.tui.widgets.artifacts.plans_data._load_proposals",
        lambda _project: (),
    )

    snapshot = load_plans_snapshot("alpha", force=True)

    assert [row.id for row in snapshot.epics] == [epic.id]
    assert [row.id for row in snapshot.phases_by_epic[epic.id]] == [
        first.id,
        second.id,
    ]
    assert first.id in snapshot.ready_ids
    assert second.id in snapshot.blocked_ids
    assert [match.plan.title for match in snapshot.archive] == ["Fixture archive"]


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
        await page.press("[")
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
        await page.press("[")
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
        return snapshot.epics[0]

    monkeypatch.setattr(
        "sase.ace.tui.actions.artifacts_plans._update_scoped_bead",
        update,
    )

    async with AcePage(initial_tab="changespecs") as page:
        await page.press("[")
        pane = page.query_one_widget("#artifacts-plans-pane", ArtifactsPlansPane)
        await page.wait_for(lambda _state: pane.snapshot is snapshot)
        await page.press("j", "s")
        await page.wait_for(lambda _state: page.app._task_queue.running_count == 0)

        tasks = page.app._task_queue.get_all()
        assert tasks[0].task_type == "bead status"
        assert tasks[0].status == "success"

    assert updates == [("alpha", "alpha-1", {"status": "in_progress"})]
