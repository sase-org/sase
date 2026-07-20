"""Resume and rollback coverage for plan-file ``sase bead work``."""

from __future__ import annotations

from pathlib import Path

import pytest

from sase.bead.cli_work_from_plan import PlanFileWorkError, work_from_plan_file
from sase.bead.cli_work_handler import BeadWorkError
from sase.bead.model import BeadTier, IssueType
from sase.bead.project import BeadProject
from sase.sdd.frontmatter import parse_frontmatter
from sase.sdd.store import SddStore
from tests.test_bead.cli_work_from_plan_helpers import EPIC_PLAN


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
        project.add_dependency(cli.id, core.id)
        project.add_dependency(verify.id, core.id)
        project.add_dependency(verify.id, cli.id)

    plan = project_dir / "sdd" / "plans" / "202607" / "rollout.md"
    plan.parent.mkdir(parents=True)
    plan.write_text(
        EPIC_PLAN.replace("tier: epic", f"tier: epic\nbead_id: {epic.id}"),
        encoding="utf-8",
    )
    launches: list[str] = []
    monkeypatch.setattr(
        "sase.bead.cli_work_handler.launch_epic_bead_work",
        lambda _project, epic_id, **_kwargs: not launches.append(epic_id),
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
    )

    assert result.epic_id == epic.id
    assert result.resumed is True
    assert result.phase_bead_ids == (core.id, cli.id, verify.id)
    assert launches == [epic.id]
    assert pushes == [True]
    with BeadProject(project_dir) as project:
        assert len(project.list_issues()) == 4


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
        "sase.bead.cli_work_handler.launch_epic_bead_work",
        lambda _project, _epic_id, **_kwargs: True,
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
        no_push=False,
        render=False,
    )

    assert second.epic_id == first.epic_id
    assert second.resumed is True
    with BeadProject(project_dir) as project:
        assert len(project.list_issues()) == 4


def test_plan_file_rejects_missing_linked_bead(
    project_dir: Path,
) -> None:
    plan = project_dir / "sdd" / "plans" / "202607" / "rollout.md"
    plan.parent.mkdir(parents=True)
    plan.write_text(
        EPIC_PLAN.replace("tier: epic", "tier: epic\nbead_id: sase-999"),
        encoding="utf-8",
    )

    with pytest.raises(PlanFileWorkError, match="remove the stale bead_id"):
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


@pytest.mark.parametrize(
    (
        "no_push",
        "expected_commit_pushes",
        "expected_rollback_push",
        "expected_terminal_pushes",
    ),
    [
        (False, [False, False, False], False, [True]),
        (True, [False, False, False], False, []),
    ],
)
def test_plan_file_rollback_suppresses_intermediate_pushes_and_syncs_once(
    project_dir: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    no_push: bool,
    expected_commit_pushes: list[bool],
    expected_rollback_push: bool | None,
    expected_terminal_pushes: list[bool],
) -> None:
    from sase.bead.cli_common import _BeadsLocation

    source = project_dir / "rollout.md"
    source.write_text(EPIC_PLAN, encoding="utf-8")
    sidecar = tmp_path / "plans-sidecar"
    with BeadProject.init(sidecar, beads_dirname="beads"):
        pass
    store = SddStore(
        storage="sidecar_repos",
        sdd_dir=sidecar,
        repo_root=sidecar,
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
    ) -> bool:
        del paths
        commit_pushes.append(push_after_commit)
        return True

    rollback_pushes: list[bool | None] = []

    def auto_commit(_message: str, **kwargs: bool) -> None:
        rollback_pushes.append(kwargs.get("push_after_commit"))

    monkeypatch.setattr("sase.sdd.files.commit_sdd_store_files", commit_store)
    monkeypatch.setattr(
        "sase.bead.epic_from_plan.auto_commit_bead_store",
        auto_commit,
    )
    terminal_pushes: list[bool] = []
    monkeypatch.setattr(
        "sase.sdd._commit_store.push_sdd_store_after_commit",
        lambda _store, *, push_after_commit: terminal_pushes.append(push_after_commit),
    )
    monkeypatch.setattr(
        "sase.bead.cli_work_handler.launch_epic_bead_work",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            BeadWorkError("agent launch failed")
        ),
    )

    with pytest.raises(PlanFileWorkError, match="agent launch failed"):
        work_from_plan_file(
            str(source),
            dry_run=False,
            yes=True,
            no_push=no_push,
            render=False,
        )

    assert commit_pushes == expected_commit_pushes
    assert rollback_pushes == [expected_rollback_push]
    assert terminal_pushes == expected_terminal_pushes
