"""Plans-pane data, navigation, and tracked-action coverage."""

from __future__ import annotations

from dataclasses import replace
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from rich.console import Console
from textual.color import Color
from textual.widgets import Markdown, OptionList

from sase.ace.testing import AcePage
from sase.ace.tui.actions.artifacts import _ArtifactsProjectChoices
from sase.ace.tui.modals.inventory_project_picker import InventoryProjectChoice
from sase.ace.tui.widgets.artifacts.plans_data import (
    PlanProposal,
    PlansSnapshot,
    ProjectArchive,
    ProjectIssue,
    load_plans_snapshot,
)
from sase.ace.tui.widgets.artifacts import plans_detail, plans_pane
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


def _all_choices() -> _ArtifactsProjectChoices:
    return _ArtifactsProjectChoices(
        choices=(
            InventoryProjectChoice(
                project_key="alpha",
                display_name="Alpha",
                state="enabled",
            ),
            InventoryProjectChoice(
                project_key="beta",
                display_name="Beta",
                state="enabled",
            ),
        ),
        enabled_projects=("alpha", "beta"),
        display_names={"alpha": "Alpha", "beta": "Beta"},
    )


def _snapshot(tmp_path: Path) -> PlansSnapshot:
    proposal_frontmatter = {
        "title": "Ship the plan browser",
        "tier": "epic",
        "status": "wip",
        "create_time": "2026-07-06 11:58:00",
        "goal": "Make plans readable and actionable across every enabled project.",
        "reviewer": "platform-ui",
    }
    proposal_body = (
        "# Ship the plan browser\n\n"
        "Aggregate every enabled project while keeping `inline code` readable."
    )
    notification = Notification(
        id="proposal-1",
        timestamp="2026-07-06T11:58:00+00:00",
        sender="planner",
        files=[str(tmp_path / "proposal.md")],
        action="PlanApproval",
        action_data={"response_dir": str(tmp_path / "approval")},
    )
    proposal = PlanProposal(
        project="alpha",
        notification=notification,
        title="Ship the plan browser",
        tier="epic",
        age="2m ago",
        timestamp=notification.timestamp,
        plan_path=notification.files[0],
        content=(
            "---\n"
            "title: Ship the plan browser\n"
            "tier: epic\n"
            "status: wip\n"
            "create_time: 2026-07-06 11:58:00\n"
            "goal: Make plans readable and actionable across every enabled project.\n"
            "reviewer: platform-ui\n"
            "---\n"
            f"{proposal_body}"
        ),
        frontmatter=proposal_frontmatter,
        body=proposal_body,
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
        created_at="2026-06-30T12:00:00Z",
        updated_at="2026-07-05T15:30:00Z",
    )
    first = Issue(
        id="alpha-1.1",
        title="Load plans",
        issue_type=IssueType.PHASE,
        parent_id=epic.id,
        model="codex/gpt-5",
        created_at="2026-07-01T09:00:00Z",
        updated_at="2026-07-05T10:00:00Z",
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
                created_at="2026-07-02T09:00:00Z",
            )
        ],
        created_at="2026-07-02T09:00:00Z",
        updated_at="2026-07-05T11:00:00Z",
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
            created_at="2026-07-04 10:00:00",
            prompt_link="",
            summary="The archived plan summary.",
            body="# Rollout\n\nDone.",
            frontmatter={
                "title": "Archived rollout",
                "tier": "epic",
                "status": "done",
                "create_time": "2026-07-04 10:00:00",
                "goal": "Record a completed rollout with its full plan metadata.",
            },
        ),
        matched_fields=[],
        score=1.0,
    )
    return PlansSnapshot(
        project="alpha",
        projects=("alpha",),
        display_names={"alpha": "Alpha"},
        beads_dirs={"alpha": str(tmp_path / "beads")},
        plans_roots={"alpha": str(tmp_path)},
        workspace_dirs={"alpha": str(tmp_path / "workspace")},
        proposals=(proposal,),
        epics=(ProjectIssue("alpha", epic),),
        phases_by_epic={
            ("alpha", epic.id): (
                ProjectIssue("alpha", first),
                ProjectIssue("alpha", second),
            )
        },
        ready_ids=frozenset({("alpha", epic.id), ("alpha", first.id)}),
        blocked_ids=frozenset({("alpha", second.id)}),
        archive=(ProjectArchive("alpha", archive),),
        source_key=("fixture",),
        errors={},
    )


def _all_projects_snapshot(tmp_path: Path) -> PlansSnapshot:
    snapshot = _snapshot(tmp_path)
    proposal = replace(snapshot.proposals[0], project="beta")
    epic = snapshot.epics[0].issue
    phases = tuple(
        ProjectIssue("beta", entry.issue)
        for entry in snapshot.phases_by_epic[("alpha", epic.id)]
    )
    archive = ProjectArchive("beta", snapshot.archive[0].match)
    return replace(
        snapshot,
        project=None,
        projects=("alpha", "beta"),
        display_names={"alpha": "Alpha", "beta": "Beta"},
        beads_dirs={
            "alpha": str(tmp_path / "alpha" / "beads"),
            "beta": str(tmp_path / "beta" / "beads"),
        },
        plans_roots={
            "alpha": str(tmp_path / "alpha"),
            "beta": str(tmp_path / "beta"),
        },
        workspace_dirs={
            "alpha": str(tmp_path / "alpha-workspace"),
            "beta": str(tmp_path / "beta-workspace"),
        },
        proposals=(proposal,),
        epics=(ProjectIssue("beta", epic),),
        phases_by_epic={("beta", epic.id): phases},
        ready_ids=frozenset(
            {
                ("beta", epic.id),
                ("beta", phases[0].issue.id),
            }
        ),
        blocked_ids=frozenset({("beta", phases[1].issue.id)}),
        archive=(archive,),
    )


def _render_detail(renderable: object) -> str:
    console = Console(width=100, color_system=None)
    with console.capture() as capture:
        console.print(renderable)
    return capture.get()


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
        "sase.ace.tui.widgets.artifacts.plans_data._resolve_projects",
        lambda _project: (
            SimpleNamespace(
                project="alpha",
                display_name="Alpha",
                workspace_dir=str(tmp_path / "workspace"),
            ),
        ),
    )
    monkeypatch.setattr(
        "sase.ace.tui.widgets.artifacts.plans_data._load_proposals",
        lambda _project, _enabled: (),
    )

    snapshot = load_plans_snapshot("alpha", force=True)

    assert [row.issue.id for row in snapshot.epics] == [epic.id]
    assert [row.issue.id for row in snapshot.phases_by_epic[("alpha", epic.id)]] == [
        first.id,
        second.id,
    ]
    assert ("alpha", first.id) in snapshot.ready_ids
    assert ("alpha", second.id) in snapshot.blocked_ids
    assert [entry.match.plan.title for entry in snapshot.archive] == ["Fixture archive"]


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
        return snapshot.epics[0].issue

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


async def test_default_scope_loads_all_projects_and_namespaces_rows(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    snapshot = _all_projects_snapshot(tmp_path)
    loaded_scopes: list[str | None] = []
    monkeypatch.setattr(
        "sase.ace.tui.actions.artifacts._collect_artifacts_project_choices",
        _all_choices,
    )

    def load(project: str | None, **_kwargs: object) -> PlansSnapshot:
        loaded_scopes.append(project)
        return snapshot

    monkeypatch.setattr(
        "sase.ace.tui.widgets.artifacts.plans_pane.load_plans_snapshot",
        load,
    )

    async with AcePage(initial_tab="changespecs") as page:
        await page.press("[")
        pane = page.query_one_widget("#artifacts-plans-pane", ArtifactsPlansPane)
        await page.wait_for(lambda _state: pane.snapshot is snapshot)

        assert loaded_scopes[0] is None
        assert pane.project_scope is None
        assert "All projects" in pane._scope_text().plain
        assert pane.selected_row() is not None
        assert pane.selected_row().project == "beta"  # type: ignore[union-attr]
        option_ids = {
            pane.query_one("#plans-list", OptionList).get_option_at_index(index).id
            for index in range(pane.query_one("#plans-list", OptionList).option_count)
        }
        assert "proposal:beta:proposal-1" in option_ids
        assert "epic:beta:alpha-1" in option_ids


async def test_picker_round_trip_back_to_all_projects(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    all_snapshot = _all_projects_snapshot(tmp_path)
    monkeypatch.setattr(
        "sase.ace.tui.actions.artifacts._collect_artifacts_project_choices",
        _all_choices,
    )

    def load(project: str | None, **_kwargs: object) -> PlansSnapshot:
        if project is None:
            return all_snapshot
        return replace(
            all_snapshot,
            project=project,
            projects=(project,),
        )

    monkeypatch.setattr(
        "sase.ace.tui.widgets.artifacts.plans_pane.load_plans_snapshot",
        load,
    )

    async with AcePage(initial_tab="changespecs") as page:
        await page.press("[")
        pane = page.query_one_widget("#artifacts-plans-pane", ArtifactsPlansPane)
        await page.wait_for(
            lambda _state: (
                pane.snapshot is not None
                and pane.snapshot.project is None
                and page.app._artifacts_project_choices is not None
            )
        )

        page.app._set_artifacts_project_scope("beta", picked=True)
        await page.wait_for(
            lambda _state: pane.snapshot is not None and pane.snapshot.project == "beta"
        )
        await page.press("p")
        await page.expect_modal("InventoryProjectPicker")
        await page.press("k", "k", "enter")
        await page.wait_for(
            lambda _state: pane.snapshot is not None and pane.snapshot.project is None
        )

        assert pane.project_scope is None
        assert "All projects" in pane._scope_text().plain


async def test_all_project_bead_actions_route_to_selected_row_project(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from textual.widgets import Input

    snapshot = _all_projects_snapshot(tmp_path)
    monkeypatch.setattr(
        "sase.ace.tui.actions.artifacts._collect_artifacts_project_choices",
        _all_choices,
    )
    monkeypatch.setattr(
        "sase.ace.tui.widgets.artifacts.plans_pane.load_plans_snapshot",
        lambda _project, **_kwargs: snapshot,
    )

    async with AcePage(initial_tab="changespecs") as page:
        await page.press("[")
        pane = page.query_one_widget("#artifacts-plans-pane", ArtifactsPlansPane)
        await page.wait_for(lambda _state: pane.snapshot is snapshot)
        await page.press("j")
        row = pane.selected_row()
        assert row is not None and row.issue is not None
        assert row.project == "beta"

        update = Mock()
        monkeypatch.setattr(page.app, "_submit_plans_bead_update", update)
        page.app.action_plans_cycle_status()
        assert update.call_args.args[1:3] == ("beta", row.issue)

        page.app.action_plans_edit_bead()
        await page.expect_modal("BeadEditModal")
        await page.pause()
        page.app.screen.query_one(
            "#bead-edit-title-input", Input
        ).value = f"{row.issue.title} updated"
        await page.press("ctrl+s")
        await page.pause()
        assert update.call_args.args[1:3] == ("beta", row.issue)

        launch = Mock()
        monkeypatch.setattr(page.app, "_submit_plans_epic_launch", launch)
        page.app.action_plans_launch_epic()
        await page.expect_modal("ConfirmActionModal")
        await page.press("y")
        await page.pause()
        assert launch.call_args.args[1:3] == ("beta", row.issue)

        tracked = Mock()
        monkeypatch.setattr(page.app, "_submit_tracked_task", tracked)
        page.app.action_plans_open_bug()
        assert tracked.call_args.args[2] == str(tmp_path / "beta-workspace")
        assert tracked.call_args.kwargs["dedup_key"] == "plans:bug:beta:42"


def test_plan_list_rows_are_compact_single_line_labels(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    snapshot = _snapshot(tmp_path)
    proposal = snapshot.proposals[0]
    epic = replace(
        snapshot.epics[0].issue,
        title="A very long epic title that must never wrap onto a second row",
        created_at="2026-05-16T12:00:00Z",
    )
    phases = tuple(
        replace(
            item.issue,
            title="A very long phase title that must never wrap onto a second row",
        )
        for item in snapshot.phases_by_epic[("alpha", "alpha-1")]
    )
    monkeypatch.setattr(
        "sase.core.time.local_now",
        lambda: datetime(2026, 7, 16, 12, 0, 0),
    )

    labels = (
        plans_pane._proposal_text(proposal),
        plans_pane._epic_text(
            epic,
            phases,
            expanded=False,
            project="alpha",
            ready_ids=snapshot.ready_ids,
            blocked_ids=snapshot.blocked_ids,
        ),
        plans_pane._phase_text(
            phases[0],
            project="alpha",
            ready_ids=snapshot.ready_ids,
            blocked_ids=snapshot.blocked_ids,
        ),
        plans_pane._archive_text(snapshot.archive[0].match),
    )
    console = Console(width=24)

    for label in labels:
        assert label.no_wrap is True
        assert label.overflow == "ellipsis"
        assert len(label.wrap(console, 24)) == 1
        assert "\n" not in label.plain

    assert labels[0].plain.endswith("epic  2m")
    assert "phases" not in labels[1].plain
    assert "alpha-cl" not in labels[1].plain
    assert "#42" not in labels[1].plain
    assert labels[1].plain.endswith("READY  2mo")
    assert "codex/gpt-5" not in labels[2].plain
    assert labels[3].plain.endswith("epic  done  07-04")


def test_project_badges_render_only_for_all_projects_scope(tmp_path: Path) -> None:
    single = _snapshot(tmp_path)
    all_projects = _all_projects_snapshot(tmp_path)
    proposal = all_projects.proposals[0]
    epic = all_projects.epics[0].issue
    phases = tuple(
        item.issue for item in all_projects.phases_by_epic[("beta", epic.id)]
    )
    archive = all_projects.archive[0].match

    all_labels = (
        plans_pane._proposal_text(
            proposal,
            project_badge=plans_pane._project_badge(all_projects, "beta"),
        ),
        plans_pane._epic_text(
            epic,
            phases,
            expanded=False,
            project="beta",
            ready_ids=all_projects.ready_ids,
            blocked_ids=all_projects.blocked_ids,
            project_badge=plans_pane._project_badge(all_projects, "beta"),
        ),
        plans_pane._archive_text(
            archive,
            project_badge=plans_pane._project_badge(all_projects, "beta"),
        ),
    )
    single_labels = (
        plans_pane._proposal_text(
            single.proposals[0],
            project_badge=plans_pane._project_badge(single, "alpha"),
        ),
        plans_pane._epic_text(
            single.epics[0].issue,
            tuple(
                item.issue
                for item in single.phases_by_epic[("alpha", single.epics[0].issue.id)]
            ),
            expanded=False,
            project="alpha",
            ready_ids=single.ready_ids,
            blocked_ids=single.blocked_ids,
            project_badge=plans_pane._project_badge(single, "alpha"),
        ),
        plans_pane._archive_text(
            single.archive[0].match,
            project_badge=plans_pane._project_badge(single, "alpha"),
        ),
    )

    assert all(label.plain.endswith("[Beta]") for label in all_labels)
    assert all("[Alpha]" not in label.plain for label in single_labels)


def test_all_projects_status_names_projects_with_load_errors(tmp_path: Path) -> None:
    pane = ArtifactsPlansPane()
    pane._snapshot = replace(
        _all_projects_snapshot(tmp_path),
        errors={"beta": "Unable to read beads"},
    )

    status = pane._status_text().plain

    assert status.startswith("2 projects")
    assert "Load errors: Beta" in status


def test_detail_properties_render_all_frontmatter_in_stable_order(
    tmp_path: Path,
) -> None:
    snapshot = _snapshot(tmp_path)
    frontmatter = {
        "zeta": "last",
        "goal": "A long goal that remains readable and wraps inside the value column.",
        "create_time": "2026-07-16 12:00:00",
        "status": "wip",
        "tier": "epic",
        "title": "Property-rich plan",
        "alpha": "first extra",
    }
    proposal = replace(snapshot.proposals[0], frontmatter=frontmatter)
    archive = replace(
        snapshot.archive[0].match,
        plan=replace(snapshot.archive[0].match.plan, frontmatter=frontmatter),
    )

    ordered_keys = [
        key for key, _value in plans_detail._ordered_frontmatter_items(frontmatter)
    ]
    proposal_detail = _render_detail(
        plans_detail.proposal_properties_header(proposal, project_name="Alpha")
    )
    archive_detail = _render_detail(
        plans_detail.archive_properties_header(archive, project_name="Alpha")
    )

    assert ordered_keys == [
        "title",
        "tier",
        "status",
        "create_time",
        "goal",
        "alpha",
        "zeta",
    ]
    for value in frontmatter.values():
        assert value in proposal_detail
        assert value in archive_detail
    assert "Source" in archive_detail
    assert "Project" in archive_detail
    assert "archive.md" in "".join(archive_detail.split())


def test_bead_detail_keeps_dependency_states_in_properties(tmp_path: Path) -> None:
    snapshot = _snapshot(tmp_path)
    dependent = snapshot.phases_by_epic[("alpha", "alpha-1")][1].issue

    detail = _render_detail(
        plans_detail.bead_properties_header(
            dependent,
            snapshot,
            project="alpha",
            project_name="Alpha",
        )
    )

    assert "Dependencies" in detail
    assert "alpha-1.1" in detail
    assert "open" in detail
    assert "blocked" in detail
    assert "Render dependency state" in detail


async def test_proposal_detail_markdown_excludes_frontmatter(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    snapshot = _snapshot(tmp_path)
    body = "# Proposal body\n\nUse `inline code` here.\n"
    proposal = replace(
        snapshot.proposals[0],
        content="---\ntitle: Hidden properties\ntier: epic\n---\n" + body,
        frontmatter={"title": "Hidden properties", "tier": "epic"},
        body=body,
    )
    snapshot = replace(snapshot, proposals=(proposal,))
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
        pane = page.query_one_widget("#artifacts-plans-pane", ArtifactsPlansPane)
        await page.wait_for(lambda _state: pane.snapshot is snapshot)
        detail = pane.query_one("#plans-detail", Markdown)

        assert detail.source == body
        assert "---" not in detail.source
        assert "title: Hidden properties" not in detail.source
        assert pane._detail_debouncer is not None
        await page.wait_for(lambda _state: bool(list(detail.query("MarkdownBlock"))))
        markdown_block = list(detail.query("MarkdownBlock"))[0]
        inline_style = markdown_block.get_component_rich_style(
            "code_inline", partial=True
        )
        expected_background = Color.parse(
            page.app.get_css_variables()["foreground"]
        ).rich_color
        assert inline_style.bgcolor == expected_background
        resolved_style = markdown_block.get_component_rich_style("code_inline")
        assert resolved_style.color is not None
        assert resolved_style.bgcolor is not None
        foreground = resolved_style.color.triplet
        background = resolved_style.bgcolor.triplet
        assert foreground is not None
        assert background is not None
        assert (
            sum(abs(foreground[index] - background[index]) for index in range(3)) > 300
        )
