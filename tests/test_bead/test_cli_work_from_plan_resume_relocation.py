"""Relocation-retry coverage for plan-file ``sase bead work``."""

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


def test_plan_file_retries_relocated_creation_and_launches_second_attempt(
    project_dir: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A relocated first attempt rolls back, publishes, and retries once."""
    from types import SimpleNamespace

    from sase.agent.launch_timing import LaunchTimingRecorder
    from sase.bead.epic_from_plan import EpicFromPlanError

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
    publications: list[str] = []
    monkeypatch.setattr(
        "sase.bead.cli_work_from_plan._publish_epic_rollback",
        lambda _store: publications.append("rollback") or True,
    )

    attempts: list[int] = []
    relaunched = SimpleNamespace(
        epic=SimpleNamespace(id="sase-42", parent_id=None),
        phases=(
            SimpleNamespace(id="sase-42.1"),
            SimpleNamespace(id="sase-42.2"),
            SimpleNamespace(id="sase-42.3"),
        ),
        dependencies=(),
    )

    def fake_create_and_launch(*_args: object, **_kwargs: object) -> object:
        from sase.sdd.frontmatter import set_frontmatter_fields

        attempts.append(1)
        if len(attempts) == 1:
            raise EpicFromPlanError(
                "epic sase-1 was renumbered to sase-99 during publication",
                graph_published=True,
                rollback_performed=True,
                relocated_epic_id="sase-99",
            )
        commit = _kwargs["commit_plan_update"]
        assert callable(commit)
        plan_path = _kwargs["plan_path"]
        content = plan_path.read_text(encoding="utf-8")
        commit(
            plan_path,
            set_frontmatter_fields(content, {"bead_id": "sase-42"}),
            "Link approved epic plan to its bead: rollout",
        )
        return relaunched

    monkeypatch.setattr(
        "sase.bead.epic_from_plan.create_and_launch_epic_from_plan",
        fake_create_and_launch,
    )

    timer = LaunchTimingRecorder("bead_work")
    result = work_from_plan_file(
        str(source),
        dry_run=False,
        yes=True,
        no_push=True,
        render=False,
        timer=timer,
    )

    assert attempts == [1, 1]
    assert publications == ["rollback"]
    assert result.epic_id == "sase-42"
    assert result.phase_bead_ids == ("sase-42.1", "sase-42.2", "sase-42.3")
    assert result.launched is True
    assert timer.fields["relocation_retries"] == 1
    archived = next((project_dir / "sdd" / "plans").glob("*/rollout.md"))
    frontmatter, _body, _had_frontmatter = parse_frontmatter(
        archived.read_text(encoding="utf-8")
    )
    assert frontmatter["bead_id"] == "sase-42"


def test_plan_file_stops_after_three_relocated_attempts(
    project_dir: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Every attempt relocated: no fourth creation, plan restored."""
    from sase.bead.epic_from_plan import EpicFromPlanError

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
    publications: list[str] = []
    monkeypatch.setattr(
        "sase.bead.cli_work_from_plan._publish_epic_rollback",
        lambda _store: publications.append("rollback") or True,
    )

    attempts: list[int] = []

    def always_relocated(*_args: object, **_kwargs: object) -> object:
        attempts.append(1)
        raise EpicFromPlanError(
            f"epic sase-{len(attempts)} was renumbered to sase-99 during publication",
            graph_published=True,
            rollback_performed=True,
            relocated_epic_id="sase-99",
        )

    monkeypatch.setattr(
        "sase.bead.epic_from_plan.create_and_launch_epic_from_plan",
        always_relocated,
    )

    with pytest.raises(PlanFileWorkError, match="renumbered") as excinfo:
        work_from_plan_file(
            str(source),
            dry_run=False,
            yes=True,
            no_push=True,
            render=False,
        )

    assert attempts == [1, 1, 1]
    assert publications == ["rollback", "rollback", "rollback"]
    assert "sase bead work" in (excinfo.value.resume_command or "")
    archived = next((project_dir / "sdd" / "plans").glob("*/rollout.md"))
    frontmatter, _body, _had_frontmatter = parse_frontmatter(
        archived.read_text(encoding="utf-8")
    )
    assert "bead_id" not in frontmatter


def test_plan_file_relocation_rollback_publication_failure_stops_retrying(
    project_dir: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An unpublished rollback never retries and keeps the relocation detail."""
    from sase.bead.epic_from_plan import EpicFromPlanError

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
    publications: list[str] = []

    def failing_publish(_store: object) -> bool:
        publications.append("rollback")
        raise RuntimeError("remote rejected")

    monkeypatch.setattr(
        "sase.bead.cli_work_from_plan._publish_epic_rollback",
        failing_publish,
    )

    attempts: list[int] = []

    def relocated(*_args: object, **_kwargs: object) -> object:
        attempts.append(1)
        raise EpicFromPlanError(
            "epic sase-1 was renumbered to sase-99 during publication",
            graph_published=True,
            rollback_performed=True,
            relocated_epic_id="sase-99",
        )

    monkeypatch.setattr(
        "sase.bead.epic_from_plan.create_and_launch_epic_from_plan",
        relocated,
    )

    with pytest.raises(PlanFileWorkError) as excinfo:
        work_from_plan_file(
            str(source),
            dry_run=False,
            yes=True,
            no_push=True,
            render=False,
        )

    assert attempts == [1]
    assert publications == ["rollback"]
    message = str(excinfo.value)
    assert "renumbered to sase-99" in message
    assert "rollback publication also failed: remote rejected" in message
    assert "sase bead work" in (excinfo.value.resume_command or "")


def test_resume_relinks_plan_to_moved_epic(
    project_dir: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A resumed epic that moved is relinked; the error names the moved ID."""
    from sase.bead.cli_work_handler import EpicGraphRelocatedError

    with BeadProject(project_dir) as project:
        epic = project.create(
            "Plan-file rollout",
            IssueType.PLAN,
            tier=BeadTier.EPIC,
        )
        for title in ("Build the core", "Add the CLI", "Verify the result"):
            project.create(title, IssueType.PHASE, parent_id=epic.id)
        moved = project.create(
            "Moved epic",
            IssueType.PLAN,
            tier=BeadTier.EPIC,
        )

    plan = project_dir / "sdd" / "plans" / "202607" / "rollout.md"
    plan.parent.mkdir(parents=True)
    plan.write_text(
        EPIC_PLAN.replace("tier: epic", f"tier: epic\nbead_id: {epic.id}"),
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
    monkeypatch.setattr(
        "sase.bead.cli_work_handler.launch_epic_bead_work",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            EpicGraphRelocatedError(epic.id, moved.id)
        ),
    )
    publications: list[str] = []
    monkeypatch.setattr(
        "sase.bead.cli_work_from_plan._publish_epic_rollback",
        lambda _store: publications.append("rollback") or True,
    )

    with pytest.raises(PlanFileWorkError) as excinfo:
        work_from_plan_file(
            str(plan),
            dry_run=False,
            yes=True,
            no_push=True,
            render=False,
        )

    assert moved.id in str(excinfo.value)
    assert "resumes the moved epic" in str(excinfo.value)
    assert publications == ["rollback"]
    frontmatter, _body, _had_frontmatter = parse_frontmatter(
        plan.read_text(encoding="utf-8")
    )
    assert frontmatter["bead_id"] == moved.id
