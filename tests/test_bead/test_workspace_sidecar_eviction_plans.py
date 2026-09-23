"""Launch-time eviction of generic sidecar clones must preserve local commits."""

from __future__ import annotations

from pathlib import Path
import subprocess

import pytest

from sase.axe import runner_workspace_sidecar as workspace_module
from sase.axe.runner_workspace import prepare_launch_workspace_repos

from .sync_conflict_regression_helpers import _git
from .sync_test_helpers import init_git_repo
from .workspace_sidecar_eviction_test_helpers import (
    _WORKSPACE_NUM,
    _bundle_holds_sha,
    _commit_remote_sidecar_file,
    _commit_sidecar_file,
    _commit_unpushed_sidecar_file,
    _damage_sidecar_unborn_head,
    _record_clone,
    _redirect_state,
    _remote_file,
    _rescue_bundles,
    _rescue_entries,
    _seed_workspace_sidecar_repo,
)


@pytest.fixture(autouse=True)
def _clear_publication_memo():
    workspace_module._FAILED_PUBLICATIONS.clear()
    yield
    workspace_module._FAILED_PUBLICATIONS.clear()


def test_eviction_quarantines_unborn_head_sidecar_and_reclones(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    workspace, plans, _remote = _seed_workspace_sidecar_repo(tmp_path)
    _damage_sidecar_unborn_head(plans)
    home, notified = _redirect_state(tmp_path, monkeypatch)
    clones: list[tuple[str, int, bool]] = []

    def recreate_plans_sidecar(
        workspace_dir: str, workspace_num: int, *, strict: bool = False
    ) -> None:
        clones.append((workspace_dir, workspace_num, strict))
        fresh = Path(workspace_dir) / "sase" / "repos" / "plans"
        fresh.mkdir(parents=True)
        init_git_repo(fresh)

    monkeypatch.setattr(
        "sase.sdd.store.ensure_workspace_sdd_clone",
        recreate_plans_sidecar,
    )

    cloned_sidecars = prepare_launch_workspace_repos(str(workspace), _WORKSPACE_NUM)

    assert clones == [(str(workspace), _WORKSPACE_NUM, True)]
    assert cloned_sidecars == {str(plans.resolve())}
    assert (plans / ".git").is_dir()
    # The damaged clone was quarantined into the durable rescue store outside
    # the workspace — never into the workspace itself — and eviction proceeded.
    assert not (workspace / ".sase" / "sidecar-quarantine").exists()
    entries = _rescue_entries(home)
    assert len(entries) == 1
    quarantined = entries[0] / "quarantined-clone"
    assert (quarantined / ".git").is_dir()
    assert len(notified) == 1
    sender, _cl_name, _success, notes, kwargs = notified[0]
    assert sender == "workspace-rescue"
    assert any("quarantin" in note for note in notes)
    assert any(str(entries[0]) in note for note in notes)
    assert kwargs["extra_files"] == [str(entries[0])]


def test_eviction_proceeds_when_damaged_sidecar_quarantine_fails(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    workspace, plans, _remote = _seed_workspace_sidecar_repo(tmp_path)
    _damage_sidecar_unborn_head(plans)
    _home, notified = _redirect_state(tmp_path, monkeypatch)
    clones: list[tuple[str, int, bool]] = []
    monkeypatch.setattr(
        "sase.workspace_provider.rescue.quarantine_directory",
        lambda *_args, **_kwargs: None,
    )
    monkeypatch.setattr(
        "sase.sdd.store.ensure_workspace_sdd_clone",
        _record_clone(clones),
    )

    prepare_launch_workspace_repos(str(workspace), _WORKSPACE_NUM)

    assert clones == [(str(workspace), _WORKSPACE_NUM, True)]
    stderr = capsys.readouterr().err
    assert "may lose local commits" in stderr
    assert "proceeding with eviction" in stderr
    assert len(notified) == 1
    sender, _cl_name, success, _notes, _kwargs = notified[0]
    assert sender == "workspace-rescue"
    assert success is False


def test_eviction_publishes_unpushed_plans_sidecar_commit(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    workspace, plans, remote = _seed_workspace_sidecar_repo(tmp_path)
    local_commit = _commit_unpushed_sidecar_file(plans)
    clones: list[tuple[str, int, bool]] = []
    monkeypatch.setattr(
        "sase.sdd.store.ensure_workspace_sdd_clone",
        _record_clone(clones),
    )

    prepare_launch_workspace_repos(str(workspace), _WORKSPACE_NUM)

    assert _git(remote, "rev-parse", "refs/heads/main").stdout.strip() == local_commit
    assert clones == [(str(workspace), _WORKSPACE_NUM, True)]
    assert not (workspace / "sase" / "repos").exists()


def test_eviction_integrates_disjoint_remote_plan_commit_before_publication(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    workspace, plans, remote = _seed_workspace_sidecar_repo(tmp_path)
    _commit_unpushed_sidecar_file(plans)
    _commit_remote_sidecar_file(
        tmp_path,
        remote,
        "202609/remote.md",
        "# Remote\n",
        "archive remote plan",
    )
    clones: list[tuple[str, int, bool]] = []
    notified: list[tuple[object, ...]] = []
    monkeypatch.setattr(
        "sase.sdd.store.ensure_workspace_sdd_clone",
        _record_clone(clones),
    )
    monkeypatch.setattr(
        "sase.notifications.notify_workflow_complete",
        lambda *args, **kwargs: notified.append((*args, kwargs)),
    )

    prepare_launch_workspace_repos(str(workspace), _WORKSPACE_NUM)

    assert _remote_file(remote, "202609/rollout.md") == "# Plan\n"
    assert _remote_file(remote, "202609/remote.md") == "# Remote\n"
    assert clones == [(str(workspace), _WORKSPACE_NUM, True)]
    assert notified == []
    assert not (workspace / "sase" / "repos").exists()


def test_eviction_converges_when_equivalent_plan_change_is_already_remote(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    workspace, plans, remote = _seed_workspace_sidecar_repo(tmp_path)
    _commit_unpushed_sidecar_file(plans)
    _commit_remote_sidecar_file(
        tmp_path,
        remote,
        "202609/rollout.md",
        "# Plan\n",
        "archive equivalent rollout plan",
    )
    clones: list[tuple[str, int, bool]] = []
    monkeypatch.setattr(
        "sase.sdd.store.ensure_workspace_sdd_clone",
        _record_clone(clones),
    )

    prepare_launch_workspace_repos(str(workspace), _WORKSPACE_NUM)

    assert _remote_file(remote, "202609/rollout.md") == "# Plan\n"
    assert clones == [(str(workspace), _WORKSPACE_NUM, True)]
    assert not (workspace / "sase" / "repos").exists()


def test_eviction_retries_when_remote_writer_wins_after_first_integration(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    workspace, plans, remote = _seed_workspace_sidecar_repo(tmp_path)
    _commit_unpushed_sidecar_file(plans)
    _commit_remote_sidecar_file(
        tmp_path,
        remote,
        "202609/first-remote.md",
        "# First\n",
        "archive first remote plan",
    )
    clones: list[tuple[str, int, bool]] = []
    push_calls = 0
    actual_push = workspace_module._run_sidecar_push

    def push_with_race(repo: Path) -> subprocess.CompletedProcess[str]:
        nonlocal push_calls
        push_calls += 1
        if push_calls == 2:
            _commit_remote_sidecar_file(
                tmp_path,
                remote,
                "202609/race.md",
                "# Race\n",
                "archive racing remote plan",
                writer_name="remote-race-writer",
            )
        return actual_push(repo)

    monkeypatch.setattr(
        "sase.axe.runner_workspace_sidecar._run_sidecar_push",
        push_with_race,
    )
    monkeypatch.setattr(
        "sase.sdd.store.ensure_workspace_sdd_clone",
        _record_clone(clones),
    )

    prepare_launch_workspace_repos(str(workspace), _WORKSPACE_NUM)

    assert push_calls == 3
    assert _remote_file(remote, "202609/rollout.md") == "# Plan\n"
    assert _remote_file(remote, "202609/first-remote.md") == "# First\n"
    assert _remote_file(remote, "202609/race.md") == "# Race\n"
    assert clones == [(str(workspace), _WORKSPACE_NUM, True)]


def test_eviction_rescues_when_remote_keeps_advancing(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    workspace, plans, remote = _seed_workspace_sidecar_repo(tmp_path)
    _commit_unpushed_sidecar_file(plans)
    home, notified = _redirect_state(tmp_path, monkeypatch)
    clones: list[tuple[str, int, bool]] = []
    push_calls = 0
    actual_push = workspace_module._run_sidecar_push

    def push_after_remote_advances(repo: Path) -> subprocess.CompletedProcess[str]:
        nonlocal push_calls
        push_calls += 1
        _commit_remote_sidecar_file(
            tmp_path,
            remote,
            f"202609/remote-{push_calls}.md",
            f"# Remote {push_calls}\n",
            f"archive remote plan {push_calls}",
            writer_name=f"advancing-writer-{push_calls}",
        )
        return actual_push(repo)

    monkeypatch.setattr(
        "sase.axe.runner_workspace_sidecar._run_sidecar_push",
        push_after_remote_advances,
    )
    monkeypatch.setattr(
        "sase.sdd.store.ensure_workspace_sdd_clone",
        _record_clone(clones),
    )

    prepare_launch_workspace_repos(str(workspace), _WORKSPACE_NUM)

    # The push policy still stops within its bound, but the launch no longer
    # fails: the local work is rescued and eviction proceeds. (Integration
    # rebased the commit, so the bundle holds the rebased HEAD carrying the
    # local file, not the original SHA.)
    assert push_calls == 3
    assert clones == [(str(workspace), _WORKSPACE_NUM, True)]
    bundles = _rescue_bundles(home)
    assert len(bundles) == 1
    probe = tmp_path / "probe-rescued"
    subprocess.run(
        ["git", "clone", "-q", str(remote), str(probe)],
        check=True,
        capture_output=True,
        text=True,
    )
    subprocess.run(
        ["git", "fetch", str(bundles[0]), "refs/*:refs/sase/rescued/x/*"],
        cwd=probe,
        check=True,
        capture_output=True,
        text=True,
    )
    rescued = subprocess.run(
        ["git", "show", "refs/sase/rescued/x/heads/main:202609/rollout.md"],
        cwd=probe,
        check=True,
        capture_output=True,
        text=True,
    ).stdout
    assert rescued == "# Plan\n"
    stderr = capsys.readouterr().err
    assert "retry limit is exhausted" in stderr
    assert str(bundles[0].parent) in stderr
    assert len(notified) == 1
    assert notified[0][0] == "workspace-rescue"


def test_eviction_rescues_sidecar_when_rebase_conflicts(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    workspace, plans, remote = _seed_workspace_sidecar_repo(tmp_path)
    local_commit = _commit_sidecar_file(
        plans,
        "README.md",
        "# local\n",
        "edit local readme",
    )
    _commit_remote_sidecar_file(
        tmp_path,
        remote,
        "README.md",
        "# remote\n",
        "edit remote readme",
    )
    home, notified = _redirect_state(tmp_path, monkeypatch)
    clones: list[tuple[str, int, bool]] = []
    monkeypatch.setattr(
        "sase.sdd.store.ensure_workspace_sdd_clone",
        _record_clone(clones),
    )

    prepare_launch_workspace_repos(str(workspace), _WORKSPACE_NUM)

    assert clones == [(str(workspace), _WORKSPACE_NUM, True)]
    # The conflicting commit was never published, but it survives in the
    # rescue bundle instead of failing the launch.
    assert _git(remote, "rev-parse", "refs/heads/main").stdout.strip() != local_commit
    bundles = _rescue_bundles(home)
    assert len(bundles) == 1
    assert _bundle_holds_sha(bundles[0], local_commit, tmp_path, remote)
    assert "git rebase failed" in capsys.readouterr().err
    assert len(notified) == 1
    assert notified[0][0] == "workspace-rescue"


def test_eviction_uses_configured_non_origin_upstream(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    workspace, plans, remote = _seed_workspace_sidecar_repo(
        tmp_path,
        branch="stable",
        remote_name="mirror",
    )
    _commit_unpushed_sidecar_file(plans)
    _commit_remote_sidecar_file(
        tmp_path,
        remote,
        "202609/mirror.md",
        "# Mirror\n",
        "archive mirror plan",
    )
    clones: list[tuple[str, int, bool]] = []
    monkeypatch.setattr(
        "sase.sdd.store.ensure_workspace_sdd_clone",
        _record_clone(clones),
    )

    prepare_launch_workspace_repos(str(workspace), _WORKSPACE_NUM)

    assert _remote_file(remote, "202609/rollout.md", ref="stable") == "# Plan\n"
    assert _remote_file(remote, "202609/mirror.md", ref="stable") == "# Mirror\n"
    assert clones == [(str(workspace), _WORKSPACE_NUM, True)]


def test_eviction_rescues_unpublished_plans_sidecar_commit(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    workspace, plans, remote = _seed_workspace_sidecar_repo(tmp_path)
    local_commit = _commit_unpushed_sidecar_file(plans)
    home, notified = _redirect_state(tmp_path, monkeypatch)
    clones: list[tuple[str, int, bool]] = []

    monkeypatch.setattr(
        "sase.axe.runner_workspace_sidecar._run_sidecar_push",
        lambda _repo: subprocess.CompletedProcess(
            ["git", "push"],
            1,
            stdout="",
            stderr="injected sidecar push failure",
        ),
    )
    monkeypatch.setattr(
        "sase.sdd.store.ensure_workspace_sdd_clone",
        _record_clone(clones),
    )

    prepare_launch_workspace_repos(str(workspace), _WORKSPACE_NUM)

    # Eviction proceeds: the unpublished commit survives in a restorable
    # rescue bundle instead of failing the launch.
    assert clones == [(str(workspace), _WORKSPACE_NUM, True)]
    assert _git(remote, "rev-parse", "refs/heads/main").stdout.strip() != local_commit
    bundles = _rescue_bundles(home)
    assert len(bundles) == 1
    assert _bundle_holds_sha(bundles[0], local_commit, tmp_path, remote)
    stderr = capsys.readouterr().err
    assert str(bundles[0].parent) in stderr
    assert "injected sidecar push failure" in stderr
    assert len(notified) == 1
    sender, _cl_name, _success, notes, kwargs = notified[0]
    assert sender == "workspace-rescue"
    assert any(str(bundles[0].parent) in note for note in notes)
    assert kwargs["extra_files"] == [str(bundles[0].parent)]
