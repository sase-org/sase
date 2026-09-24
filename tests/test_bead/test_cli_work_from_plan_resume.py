"""Resume and rollback coverage for plan-file ``sase bead work``."""

from __future__ import annotations

from pathlib import Path
import subprocess

import pytest

from sase.bead.cli_work_from_plan import PlanFileWorkError, work_from_plan_file
from sase.bead.cli_work_handler import BeadWorkError
from sase.bead.model import BeadTier, IssueType
from sase.bead.project import BeadProject
from sase.sdd.frontmatter import parse_frontmatter
from sase.sdd.store import SddStore
from tests.test_bead.cli_work_from_plan_helpers import EPIC_PLAN, write_plan_update
from tests.test_bead.sync_test_helpers import configure_git_identity


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


def test_plan_file_launch_failure_rolls_back_for_resume(
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
    monkeypatch.setattr(
        "sase.bead.cli_work_handler.launch_epic_bead_work",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            BeadWorkError("agent launch failed")
        ),
    )

    with pytest.raises(PlanFileWorkError, match="agent launch failed") as excinfo:
        work_from_plan_file(
            str(source),
            dry_run=False,
            yes=True,
            no_push=True,
            render=False,
        )

    assert "sase bead work" in (excinfo.value.resume_command or "")
    assert "--no-push" in (excinfo.value.resume_command or "")
    with BeadProject(project_dir) as project:
        assert project.list_issues() == []
    archived = next((project_dir / "sdd" / "plans").glob("*/rollout.md"))
    frontmatter, _body, _had_frontmatter = parse_frontmatter(
        archived.read_text(encoding="utf-8")
    )
    assert "bead_id" not in frontmatter


def test_plan_file_launch_failure_resume_command_preserves_capacity(
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
    monkeypatch.setattr(
        "sase.bead.cli_work_handler.launch_epic_bead_work",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            BeadWorkError("agent launch failed")
        ),
    )

    with pytest.raises(PlanFileWorkError, match="agent launch failed") as excinfo:
        work_from_plan_file(
            str(source),
            dry_run=False,
            yes=True,
            no_push=True,
            render=False,
            capacity=1,
        )

    resume = excinfo.value.resume_command or ""
    assert "--capacity 1" in resume
    assert "--no-push" in resume
    with BeadProject(project_dir) as project:
        assert project.list_issues() == []


def test_stale_link_replacement_launch_failure_restores_stale_link(
    project_dir: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    plan = project_dir / "sdd" / "plans" / "202607" / "rollout.md"
    plan.parent.mkdir(parents=True)
    original = EPIC_PLAN.replace("tier: epic", "tier: epic\nbead_id: sase-999")
    plan.write_text(original, encoding="utf-8")
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
            BeadWorkError("agent launch failed")
        ),
    )

    with pytest.raises(PlanFileWorkError, match="agent launch failed"):
        work_from_plan_file(
            str(plan),
            dry_run=False,
            yes=True,
            no_push=True,
            render=False,
        )

    with BeadProject(project_dir) as project:
        assert project.list_issues() == []
    assert plan.read_text(encoding="utf-8") == original
    frontmatter, _body, _had_frontmatter = parse_frontmatter(
        plan.read_text(encoding="utf-8")
    )
    assert frontmatter["bead_id"] == "sase-999"


def test_zero_spawn_after_publication_commits_and_publishes_rollback(
    project_dir: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from sase.bead.cli_common import _BeadsLocation

    source = project_dir / "rollout.md"
    source.write_text(EPIC_PLAN, encoding="utf-8")
    sidecar = tmp_path / "plans-sidecar"
    with BeadProject.init(sidecar, beads_dirname="beads"):
        pass
    subprocess.run(
        ["git", "init", "-b", "main"],
        cwd=sidecar,
        check=True,
        capture_output=True,
    )
    configure_git_identity(sidecar)
    subprocess.run(["git", "add", "."], cwd=sidecar, check=True)
    subprocess.run(
        ["git", "commit", "-m", "Initialize plans sidecar"],
        cwd=sidecar,
        check=True,
        capture_output=True,
    )
    store = SddStore(
        storage="sidecar_repos",
        sdd_dir=sidecar,
        repo_root=sidecar,
        remote_url="git@example.test:plans.git",
    )
    location = _BeadsLocation(
        root=sidecar,
        beads_dirname="beads",
        storage=store.storage,
        store=store,
    )
    monkeypatch.setattr(
        "sase.bead.cli_work_from_plan._resolve_context",
        lambda *, dry_run: (location, store, project_dir),
    )
    commit_pushes: list[bool] = []

    def commit_store(
        _store: SddStore,
        _message: str,
        *,
        paths: list[Path],
        push_after_commit: bool,
        already_locked: bool = False,
    ) -> bool:
        del paths
        assert already_locked is not _message.startswith("Archive approved plan")
        commit_pushes.append(push_after_commit)
        return True

    monkeypatch.setattr("sase.sdd.files.commit_sdd_store_files", commit_store)
    monkeypatch.setattr(
        "sase.bead.sync.commit_epic_graph_checkpoint",
        lambda *_args, **_kwargs: True,
    )
    monkeypatch.setattr(
        "sase.bead.sync.bead_state_is_clean",
        lambda _beads_dir: True,
    )
    publications: list[str] = []
    monkeypatch.setattr(
        "sase.bead.cli_work_from_plan._publish_epic_graph_before_launch",
        lambda _store, *, no_push: publications.append("graph") or True,
    )
    monkeypatch.setattr(
        "sase.bead.cli_work_from_plan._publish_epic_rollback",
        lambda _store: publications.append("rollback") or True,
    )

    def fail_after_publication(
        project: BeadProject,
        epic_id: str,
        **kwargs: object,
    ) -> bool:
        project.mark_ready_to_work(epic_id)
        before_agent_launch = kwargs["before_agent_launch"]
        assert callable(before_agent_launch)
        before_agent_launch(project, epic_id)
        raise BeadWorkError(
            "agent launch failed",
            graph_published=True,
        )

    monkeypatch.setattr(
        "sase.bead.cli_work_handler.launch_epic_bead_work",
        fail_after_publication,
    )

    with pytest.raises(PlanFileWorkError, match="agent launch failed"):
        work_from_plan_file(
            str(source),
            dry_run=False,
            yes=True,
            no_push=False,
            render=False,
        )

    assert commit_pushes == [False, False, False]
    assert publications == ["graph", "rollback"]
    with BeadProject(sidecar, beads_dirname="beads") as project:
        assert project.list_issues() == []


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
