"""Launch-failure rollback coverage for plan-file ``sase bead work``."""

from __future__ import annotations

from pathlib import Path
import subprocess

import pytest

from sase.bead.cli_work_from_plan import PlanFileWorkError, work_from_plan_file
from sase.bead.cli_work_handler import BeadWorkError
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
