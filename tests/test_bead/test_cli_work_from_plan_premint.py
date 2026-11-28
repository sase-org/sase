"""Pre-mint refresh and launch-base coverage for plan-file epic launches."""

from __future__ import annotations

from pathlib import Path
import subprocess

import pytest

from sase.agent.launch_timing import LaunchTimingRecorder
from sase.bead._sync_refresh import BeadStoreRefreshError
from sase.bead.cli_work_from_plan import PlanFileWorkError, work_from_plan_file
from sase.bead.cli_work_from_plan_premint import PRE_MINT_REFRESH_LOCK_TIMEOUT_SECONDS
from sase.bead.model import IssueType
from sase.bead.project import BeadProject
from sase.sdd._repository_types import SddIntegrationStatus
from sase.sdd.store import SDD_STORAGE_IN_TREE, SddStore
from tests.test_bead.cli_work_from_plan_helpers import EPIC_PLAN, write_plan_update
from tests.test_bead.sync_test_helpers import configure_git_identity, init_git_repo


@pytest.fixture(autouse=True)
def _stable_plan_formatting(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "sase.file_references.format_with_prettier",
        lambda content: content,
    )


def _stub_plan_launch(
    monkeypatch: pytest.MonkeyPatch,
    *,
    launches: list[str] | None = None,
) -> list[str]:
    captured = launches if launches is not None else []
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
        lambda _project, epic_id, **_kwargs: not captured.append(epic_id),
    )
    return captured


def _raise_refresh(status: SddIntegrationStatus, message: str = "refresh failed"):
    def _raise(_beads_dir: Path, *, lock_timeout: float | None = None) -> None:
        del lock_timeout
        raise BeadStoreRefreshError(message, status=status)

    return _raise


@pytest.mark.parametrize(
    "status",
    [
        SddIntegrationStatus.REMOTE_UNAVAILABLE,
        SddIntegrationStatus.TIMED_OUT,
        SddIntegrationStatus.LOCK_UNAVAILABLE,
    ],
)
def test_transient_pre_mint_refresh_proceeds_to_mint(
    project_dir: Path,
    monkeypatch: pytest.MonkeyPatch,
    status: SddIntegrationStatus,
) -> None:
    source = project_dir / "rollout.md"
    source.write_text(EPIC_PLAN, encoding="utf-8")
    launches = _stub_plan_launch(monkeypatch)
    refresh_timeouts: list[float | None] = []

    def refresh(_beads_dir: Path, *, lock_timeout: float | None = None) -> None:
        refresh_timeouts.append(lock_timeout)
        raise BeadStoreRefreshError("transient", status=status)

    monkeypatch.setattr("sase.bead.sync.refresh_bead_store", refresh)

    result = work_from_plan_file(
        str(source),
        dry_run=False,
        yes=True,
        no_push=False,
        render=False,
    )

    assert result.epic_id is not None
    assert result.resumed is False
    assert launches == [result.epic_id]
    assert refresh_timeouts
    assert all(
        timeout == PRE_MINT_REFRESH_LOCK_TIMEOUT_SECONDS for timeout in refresh_timeouts
    )
    with BeadProject(project_dir) as project:
        assert project.show(result.epic_id).issue_type is IssueType.PLAN


def test_conflicting_pre_mint_refresh_stops_before_creating_beads(
    project_dir: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = project_dir / "rollout.md"
    source.write_text(EPIC_PLAN, encoding="utf-8")
    _stub_plan_launch(monkeypatch)
    monkeypatch.setattr(
        "sase.bead.sync.refresh_bead_store",
        _raise_refresh(
            SddIntegrationStatus.ABORTED_UNSUPPORTED_CONFLICTS,
            "duplicate issue_created event for sase-1",
        ),
    )
    with BeadProject(project_dir) as project:
        before = [issue.id for issue in project.list_issues()]

    with pytest.raises(PlanFileWorkError, match="nothing was created") as caught:
        work_from_plan_file(
            str(source),
            dry_run=False,
            yes=True,
            no_push=False,
            render=False,
        )

    assert "duplicate issue_created event for sase-1" in str(caught.value)
    assert str(project_dir / "sdd" / "beads") in str(caught.value)
    with BeadProject(project_dir) as project:
        assert [issue.id for issue in project.list_issues()] == before


def test_unrecoverable_pre_mint_refresh_stops_before_creating_beads(
    project_dir: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = project_dir / "rollout.md"
    source.write_text(EPIC_PLAN, encoding="utf-8")
    _stub_plan_launch(monkeypatch)
    monkeypatch.setattr(
        "sase.bead.sync.refresh_bead_store",
        _raise_refresh(SddIntegrationStatus.UNRECOVERABLE, "store poisoned"),
    )

    with pytest.raises(PlanFileWorkError, match="nothing was created"):
        work_from_plan_file(
            str(source),
            dry_run=False,
            yes=True,
            no_push=False,
            render=False,
        )


def test_pre_mint_refresh_records_launch_base(
    project_dir: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = project_dir / "rollout.md"
    source.write_text(EPIC_PLAN, encoding="utf-8")
    _stub_plan_launch(monkeypatch)
    monkeypatch.setattr(
        "sase.bead.sync.refresh_bead_store",
        lambda *_args, **_kwargs: None,
    )
    monkeypatch.setattr(
        "sase.bead.sync.bead_store_head_sha",
        lambda _beads_dir: "abc123def",
    )
    timer = LaunchTimingRecorder(operation="pre-mint-test")

    work_from_plan_file(
        str(source),
        dry_run=False,
        yes=True,
        no_push=False,
        render=False,
        timer=timer,
    )

    assert timer.fields["launch_base"] == "abc123def"


def _git(repo: Path, *args: str) -> None:
    subprocess.run(
        ["git", *args],
        cwd=repo,
        check=True,
        capture_output=True,
        text=True,
    )


def _commit(repo: Path, message: str) -> None:
    _git(repo, "add", "-A")
    _git(repo, "commit", "-m", message)


def test_pre_mint_refresh_makes_a_remote_mint_visible(
    project_dir: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from sase.bead.cli_common import BeadsLocation

    remote = tmp_path / "beads.git"
    subprocess.run(
        ["git", "init", "--bare", "-b", "main", str(remote)],
        check=True,
        capture_output=True,
        text=True,
    )
    seed = tmp_path / "seed"
    seed.mkdir()
    init_git_repo(seed)
    _git(seed, "branch", "-M", "main")
    (seed / ".gitignore").write_text("beads/beads.db*\n", encoding="utf-8")
    with BeadProject.init(seed, beads_dirname="beads"):
        pass
    _commit(seed, "seed empty bead store")
    _git(seed, "remote", "add", "origin", str(remote))
    _git(seed, "push", "-u", "origin", "main")

    clone_a = tmp_path / "clone-a"
    clone_b = tmp_path / "clone-b"
    subprocess.run(
        ["git", "clone", str(remote), str(clone_a)],
        check=True,
        capture_output=True,
        text=True,
    )
    subprocess.run(
        ["git", "clone", str(remote), str(clone_b)],
        check=True,
        capture_output=True,
        text=True,
    )
    configure_git_identity(clone_a)
    configure_git_identity(clone_b)

    with BeadProject(clone_a, beads_dirname="beads") as project:
        remote_issue = project.create(
            "Published elsewhere",
            IssueType.TASK,
            task_type="bug",
            size="small",
        )
        project.sync()
    _commit(clone_a, "publish remote mint")
    _git(clone_a, "push", "origin", "main")

    with BeadProject(clone_b, beads_dirname="beads") as project:
        assert remote_issue.id not in {issue.id for issue in project.list_issues()}

    source = project_dir / "rollout.md"
    source.write_text(EPIC_PLAN, encoding="utf-8")
    launches = _stub_plan_launch(monkeypatch)
    store = SddStore(
        storage=SDD_STORAGE_IN_TREE,
        sdd_dir=project_dir / "sdd",
        repo_root=project_dir,
    )
    location = BeadsLocation(
        root=clone_b,
        beads_dirname="beads",
        storage="sidecar_repos",
        store=store,
    )
    monkeypatch.setattr(
        "sase.bead.cli_work_from_plan._resolve_context",
        lambda *, dry_run, bead_context=None: (location, store, project_dir),
    )

    def pull_refresh(beads_dir: Path, *, lock_timeout: float | None = None) -> None:
        assert lock_timeout == PRE_MINT_REFRESH_LOCK_TIMEOUT_SECONDS
        repo = beads_dir.parent
        _git(repo, "fetch", "origin")
        _git(repo, "merge", "--ff-only", "origin/main")

    monkeypatch.setattr("sase.bead.sync.refresh_bead_store", pull_refresh)

    result = work_from_plan_file(
        str(source),
        dry_run=False,
        yes=True,
        no_push=False,
        render=False,
    )

    assert result.epic_id is not None
    assert result.epic_id != remote_issue.id
    assert result.resumed is False
    assert launches == [result.epic_id]
    with BeadProject(clone_b, beads_dirname="beads") as project:
        ids = {issue.id for issue in project.list_issues()}
        assert remote_issue.id in ids
        assert result.epic_id in ids
