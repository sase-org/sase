"""Role and bead-lane tests for associated-plan enrichment."""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest

import sase.ace.tui.models.agent_associated_plan as plan_model
from sase.ace.tui.models.agent_associated_plan import resolve_agent_plan_enrichment
from sase.bead.model import BeadNote, Issue, IssueType, PhaseSize, TaskPlusOneEvidence
from tests.ace.tui.models._agent_associated_plan_helpers import write_epic, write_plan
from tests.ace.tui.widgets._agent_display_helpers import make_agent


@pytest.fixture(autouse=True)
def _clear_plan_caches() -> Iterator[None]:
    plan_model._PLAN_FILE_CACHE.clear()
    plan_model._PLAN_ASSOCIATION_CACHE.clear()
    yield
    plan_model._PLAN_FILE_CACHE.clear()
    plan_model._PLAN_ASSOCIATION_CACHE.clear()


@pytest.mark.parametrize(
    ("agent_name", "epic_bead_id", "expected_role"),
    [
        ("planner", "sase-1", "author"),
        ("sase-1", "sase-1", "land"),
        ("sase-1.land", None, "land"),
        ("sase-1", None, "land"),
    ],
    ids=["author", "modern-land", "legacy-dot-land", "legacy-exact-land"],
)
def test_epic_author_and_land_roles_keep_complete_plan(
    tmp_path: Path,
    agent_name: str,
    epic_bead_id: str | None,
    expected_role: str,
) -> None:
    plan = write_epic(tmp_path / "plans" / "epic.md")
    enrichment = resolve_agent_plan_enrichment(
        make_agent(
            agent_name=agent_name,
            epic_bead_id=epic_bead_id,
            sdd_plan_path="plans/epic.md",
            plan_committed=True,
            workspace_dir=str(tmp_path),
        )
    )

    assert enrichment.role == expected_role
    assert enrichment.associated_plan is not None
    assert enrichment.associated_plan.actual_path == str(plan.resolve())
    assert len(enrichment.associated_plan.phases) == 4
    assert tuple(phase.size for phase in enrichment.associated_plan.phases) == (
        "small",
        "small",
        "medium",
        "large",
    )


def test_legacy_dotted_phase_defaults_to_suppressed_plan_when_unconfirmed(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    write_epic(tmp_path / "plans" / "epic.md")
    monkeypatch.setattr(plan_model, "_lookup_issue", lambda *_args, **_kwargs: None)

    enrichment = resolve_agent_plan_enrichment(
        make_agent(
            agent_name="sase-1.2",
            sdd_plan_path="plans/epic.md",
            plan_committed=True,
            workspace_dir=str(tmp_path),
        )
    )

    assert enrichment.role == "phase"
    assert enrichment.associated_plan is None
    assert enrichment.phase_bead is None
    assert enrichment.resolved_plan_paths == ()


def test_explicit_phase_role_recovers_missing_phase_id_without_bead_lookup(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    plan = write_epic(tmp_path / "plans" / "epic.md")
    agent = make_agent(
        agent_name="sase-1.2",
        agent_family_role="phase",
        epic_bead_id="sase-1",
        epic_plan_ref="plans/epic.md",
        sdd_plan_path="plans/epic.md",
        plan_committed=True,
        workspace_dir=str(tmp_path),
    )
    monkeypatch.setattr(
        plan_model,
        "_lookup_issue",
        lambda *_args, **_kwargs: pytest.fail("explicit phase must not read beads"),
    )

    enrichment = resolve_agent_plan_enrichment(agent)

    assert enrichment.role == "phase"
    assert enrichment.phase_bead is not None
    assert enrichment.phase_bead.id == "sase-1.2"
    assert enrichment.phase_bead.description == (
        "Phase `docs` in approved epic plan `plans/epic.md`."
    )
    assert enrichment.phase_bead.epic_title == "Epic phase metadata"
    assert enrichment.phase_bead.actual_plan_path == str(plan.resolve())
    assert enrichment.phase_bead.display_plan_path == "plans/epic.md"
    assert enrichment.associated_plan is None
    assert enrichment.resolved_plan_path == str(plan.resolve())


def test_explicit_phase_role_without_bead_identity_stays_phase_local(
    tmp_path: Path,
) -> None:
    plan = write_epic(tmp_path / "plans" / "epic.md")

    enrichment = resolve_agent_plan_enrichment(
        make_agent(
            agent_name="phase-worker",
            agent_family_role="phase",
            epic_bead_id="sase-1",
            epic_plan_ref="plans/epic.md",
            sdd_plan_path="plans/epic.md",
            plan_committed=True,
            workspace_dir=str(tmp_path),
        )
    )

    assert enrichment.role == "phase"
    assert enrichment.phase_bead is None
    assert enrichment.associated_plan is None
    assert enrichment.resolved_plan_path == str(plan.resolve())


@pytest.mark.parametrize("task_id", ("sase-task", "sase-task.4"))
def test_task_worker_resolves_to_plan_free_task_bead_lane(
    task_id: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    task = Issue(
        id=task_id,
        title="Implement task surfaces",
        issue_type=IssueType.TASK,
        description="Render task metadata without reading a plan file.",
        size=PhaseSize.MEDIUM,
        created_at="2026-08-01T14:30:00Z",
        notes=[
            BeadNote(
                id="note-1",
                timestamp="2026-08-01T14:03:00Z",
                author="alice",
                text="first note\ncontinued line",
            ),
            BeadNote(
                id="note-2",
                timestamp="2026-08-01T14:07:00Z",
                author="bob",
                text="second note",
            ),
        ],
        plus_one_evidence=[
            TaskPlusOneEvidence(
                timestamp="2026-08-01T15:00:00Z",
                reporter="agent.beta",
                note="Independent reproduction.",
            )
        ],
    )
    monkeypatch.setattr(
        plan_model,
        "_lookup_issue",
        lambda _agent, bead_id, **_kwargs: task if bead_id == task.id else None,
    )
    # An ambient SDD reference is not authored-plan handoff evidence for a task row.
    monkeypatch.setattr(
        plan_model,
        "_load_plan_metadata",
        lambda *_args, **_kwargs: pytest.fail("task agents must not read plans"),
    )

    enrichment = resolve_agent_plan_enrichment(
        make_agent(
            agent_name=task_id,
            step_type="bash",
            sdd_plan_path="plans/task-must-not-resolve.md",
        )
    )

    assert enrichment.role == "task"
    assert enrichment.associated_plan is None
    assert enrichment.resolved_plan_paths == ()
    assert enrichment.bead_summary is not None
    assert enrichment.bead_summary.id == task_id
    assert enrichment.bead_summary.bead_type == "task"
    assert enrichment.bead_summary.title == task.title
    assert enrichment.bead_summary.description == task.description
    assert enrichment.bead_summary.size == "medium"
    assert enrichment.bead_summary.created_at == task.created_at
    assert enrichment.bead_summary.notes == (
        "[2026-08-01T14:03:00Z · alice] first note\n"
        "continued line\n\n"
        "[2026-08-01T14:07:00Z · bob] second note"
    )
    assert enrichment.bead_summary.plus_one_count == 1
    assert enrichment.bead_summary.plus_one_evidence == tuple(task.plus_one_evidence)
    assert enrichment.bead_summary.display_plan_path is None


@pytest.mark.parametrize("task_id", ("sase-task", "sase-task.4"))
def test_task_worker_with_authored_plan_shows_bead_and_plan(
    tmp_path: Path,
    task_id: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    workspace = tmp_path / "workspace"
    archived = write_plan(
        tmp_path / "archive" / "task_handoff.md",
        "Show the authored task plan beside the task bead.",
        title="Task authored handoff",
    )
    selected_plan = write_plan(
        workspace / "plans" / "task_handoff.md",
        "Show the authored task plan beside the task bead.",
        title="Task authored handoff",
    )
    task = Issue(
        id=task_id,
        title="Implement task surfaces",
        issue_type=IssueType.TASK,
        description="Render task metadata with an authored plan.",
        size=PhaseSize.MEDIUM,
    )
    monkeypatch.setattr(
        plan_model,
        "_lookup_issue",
        lambda _agent, bead_id, **_kwargs: task if bead_id == task.id else None,
    )

    enrichment = resolve_agent_plan_enrichment(
        make_agent(
            agent_name=f"{task_id}--plan",
            agent_family_role="root",
            role_suffix="--plan",
            archived_plan_path=str(archived),
            sdd_plan_path="plans/task_handoff.md",
            plan_committed=True,
            plan_action="tale",
            workspace_dir=str(workspace),
        )
    )

    assert enrichment.role == "task"
    assert enrichment.bead_summary is not None
    assert enrichment.bead_summary.bead_type == "task"
    assert enrichment.associated_plan is not None
    assert enrichment.associated_plan.title == "Task authored handoff"
    assert enrichment.associated_plan.goal == (
        "Show the authored task plan beside the task bead."
    )
    assert enrichment.associated_plan.effective_tier == "tale"
    assert enrichment.resolved_plan_paths == (str(selected_plan.resolve()),)


def test_task_worker_with_pending_authored_plan_uses_archive(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    task = Issue(
        id="sase-task",
        title="Review pending handoff",
        issue_type=IssueType.TASK,
        description="Show the uncommitted archived plan.",
    )
    archived = write_plan(
        tmp_path / "archive" / "pending_task_plan.md",
        "Keep pending task plans visible.",
        title="Pending task plan",
    )
    monkeypatch.setattr(
        plan_model,
        "_lookup_issue",
        lambda _agent, bead_id, **_kwargs: task if bead_id == task.id else None,
    )

    enrichment = resolve_agent_plan_enrichment(
        make_agent(
            agent_name=task.id,
            archived_plan_path=str(archived),
        )
    )

    assert enrichment.role == "task"
    assert enrichment.bead_summary is not None
    assert enrichment.bead_summary.bead_type == "task"
    assert enrichment.associated_plan is not None
    assert enrichment.associated_plan.actual_path == str(archived.resolve())
    assert enrichment.associated_plan.effective_tier == "plan"
    assert enrichment.associated_plan.committed is False
    assert enrichment.resolved_plan_paths == (str(archived.resolve()),)


def test_task_bead_design_does_not_become_plan_lane(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    workspace = tmp_path / "workspace"
    write_plan(
        workspace / "plans" / "task_design.md",
        "This task design is not the worker's authored plan.",
        title="Task design",
    )
    task = Issue(
        id="sase-task",
        title="Task with design",
        issue_type=IssueType.TASK,
        description="Keep the task bead lane plan-free.",
        design="plans/task_design.md",
    )
    monkeypatch.setattr(
        plan_model,
        "_lookup_issue",
        lambda _agent, bead_id, **_kwargs: task if bead_id == task.id else None,
    )
    monkeypatch.setattr(
        plan_model,
        "_load_plan_metadata",
        lambda *_args, **_kwargs: pytest.fail("task design must not be read as a plan"),
    )

    enrichment = resolve_agent_plan_enrichment(
        make_agent(
            agent_name=task.id,
            workspace_dir=str(workspace),
        )
    )

    assert enrichment.role == "task"
    assert enrichment.bead_summary is not None
    assert enrichment.bead_summary.bead_type == "task"
    assert enrichment.associated_plan is None
    assert enrichment.resolved_plan_paths == ()
