"""Resume-link coverage for plan-file ``sase bead work``."""

from __future__ import annotations

from pathlib import Path

import pytest

from sase.bead.cli_work_from_plan import PlanFileWorkError, work_from_plan_file
from sase.bead.model import BeadTier, IssueType
from sase.bead.project import BeadProject
from sase.sdd.frontmatter import parse_frontmatter
from tests.test_bead.cli_work_from_plan_helpers import EPIC_PLAN, write_plan_update


@pytest.fixture(autouse=True)
def _stable_plan_formatting(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "sase.file_references.format_with_prettier",
        lambda content: content,
    )


def test_plan_file_resume_reuses_linked_epic(
    project_dir: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    with BeadProject(project_dir) as project:
        epic = project.create(
            "Plan-file rollout",
            IssueType.PLAN,
            tier=BeadTier.EPIC,
        )
        core = project.create("Build the core", IssueType.PHASE, parent_id=epic.id)
        cli = project.create("Add the CLI", IssueType.PHASE, parent_id=epic.id)
        verify = project.create("Verify the result", IssueType.PHASE, parent_id=epic.id)
        child_epic = project.create(
            "Nested epic",
            IssueType.PLAN,
            parent_id=epic.id,
            tier=BeadTier.EPIC,
        )
        project.add_dependency(cli.id, core.id)
        project.add_dependency(verify.id, core.id)
        project.add_dependency(verify.id, cli.id)

    plan = project_dir / "sdd" / "plans" / "202607" / "rollout.md"
    plan.parent.mkdir(parents=True)
    plan.write_text(
        EPIC_PLAN.replace("tier: epic", f"tier: epic\nbead_id: {epic.id}"),
        encoding="utf-8",
    )
    launches: list[tuple[str, bool, int | None]] = []

    def launch(
        _project: BeadProject,
        epic_id: str,
        **kwargs: object,
    ) -> bool:
        capacity = kwargs["capacity"]
        assert capacity is None or isinstance(capacity, int)
        launches.append((epic_id, bool(kwargs["yes_to_all"]), capacity))
        return True

    monkeypatch.setattr(
        "sase.bead.cli_work_handler.launch_epic_bead_work",
        launch,
    )
    pushes: list[bool] = []
    monkeypatch.setattr(
        "sase.sdd._commit_store.push_sdd_store_after_commit",
        lambda _store, *, push_after_commit: pushes.append(push_after_commit),
    )

    result = work_from_plan_file(
        str(plan),
        dry_run=False,
        yes=True,
        no_push=False,
        render=False,
        capacity=1,
    )

    assert result.epic_id == epic.id
    assert result.resumed is True
    assert result.phase_bead_ids == (core.id, cli.id, verify.id)
    assert child_epic.id not in result.phase_bead_ids
    assert launches == [(epic.id, False, 1)]
    assert pushes == [True]
    with BeadProject(project_dir) as project:
        assert len(project.list_issues()) == 5


def test_retrying_original_file_preserves_archived_bead_link(
    project_dir: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = project_dir / "rollout.md"
    source.write_text(EPIC_PLAN, encoding="utf-8")
    monkeypatch.setattr(
        "sase.bead.cli_work_from_plan._commit_plan_file",
        lambda *_args, **_kwargs: True,
    )
    monkeypatch.setattr(
        "sase.bead.cli_work_from_plan._write_and_commit_plan_file",
        write_plan_update,
    )
    confirmations: list[bool] = []
    monkeypatch.setattr(
        "sase.bead.cli_work_handler.launch_epic_bead_work",
        lambda _project, _epic_id, **kwargs: (
            confirmations.append(bool(kwargs["yes_to_all"])) or True
        ),
    )

    first = work_from_plan_file(
        str(source),
        dry_run=False,
        yes=True,
        no_push=False,
        render=False,
    )
    second = work_from_plan_file(
        str(source),
        dry_run=False,
        yes=True,
        yes_to_all=True,
        no_push=False,
        render=False,
    )

    assert second.epic_id == first.epic_id
    assert second.resumed is True
    assert confirmations == [False, True]
    with BeadProject(project_dir) as project:
        assert len(project.list_issues()) == 4


def test_plan_file_replaces_missing_linked_bead(
    project_dir: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    plan = project_dir / "sdd" / "plans" / "202607" / "rollout.md"
    plan.parent.mkdir(parents=True)
    plan.write_text(
        EPIC_PLAN.replace("tier: epic", "tier: epic\nbead_id: sase-999"),
        encoding="utf-8",
    )
    monkeypatch.setattr(
        "sase.bead.cli_work_from_plan._commit_plan_file",
        lambda *_args, **_kwargs: True,
    )
    monkeypatch.setattr(
        "sase.bead.cli_work_from_plan._write_and_commit_plan_file",
        write_plan_update,
    )
    launches: list[str] = []
    monkeypatch.setattr(
        "sase.bead.cli_work_handler.launch_epic_bead_work",
        lambda _project, epic_id, **_kwargs: not launches.append(epic_id),
    )

    result = work_from_plan_file(
        str(plan),
        dry_run=False,
        yes=True,
        no_push=False,
        render=False,
    )

    assert result.epic_id is not None
    epic_id = result.epic_id
    assert epic_id != "sase-999"
    assert result.replaced_stale_epic_id == "sase-999"
    assert result.resumed is False
    assert launches == [epic_id]
    assert result.phase_bead_ids == (
        f"{epic_id}.1",
        f"{epic_id}.2",
        f"{epic_id}.3",
    )
    frontmatter, _body, _had_frontmatter = parse_frontmatter(
        plan.read_text(encoding="utf-8")
    )
    assert frontmatter["bead_id"] == epic_id
    with BeadProject(project_dir) as project:
        with pytest.raises(KeyError):
            project.show("sase-999")
        assert project.show(epic_id).tier is BeadTier.EPIC
        assert [phase.id for phase in project.get_epic_children(epic_id)] == [
            *result.phase_bead_ids
        ]


def test_plan_file_rejects_linked_non_epic_bead(
    project_dir: Path,
) -> None:
    with BeadProject(project_dir) as project:
        task = project.create(
            "Follow-up", IssueType.TASK, task_type="bug", size="small"
        )
    plan = project_dir / "sdd" / "plans" / "202607" / "rollout.md"
    plan.parent.mkdir(parents=True)
    plan.write_text(
        EPIC_PLAN.replace("tier: epic", f"tier: epic\nbead_id: {task.id}"),
        encoding="utf-8",
    )

    with pytest.raises(PlanFileWorkError, match="not an epic plan bead"):
        work_from_plan_file(
            str(plan),
            dry_run=False,
            yes=True,
            no_push=False,
            render=False,
        )
